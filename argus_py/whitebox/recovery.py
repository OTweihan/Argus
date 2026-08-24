"""白盒作业启动恢复（O-04，item 6）。

Worker 重启后扫描租约过期的 WHITEBOX+RUNNING 任务，按远端作业状态重新接管，
不再静默遗留孤儿作业：

- ``SUCCEEDED`` → 拉取已完成结果并落 COMPLETED（重新接管已完成结果）；
- ``PENDING/RUNNING`` → 任务重置 PENDING 重新入队，幂等 clientRequestId 复用
  同一远端 job 恢复轮询（重新接管运行中作业）；
- ``TIMED_OUT`` → 任务落 TIMEOUT；
- ``CANCELLED/FAILED/EXPIRED/NO_JOB/UNREACHABLE`` → 任务落 FAILED 并携带远端状态。

仅持有数据库/storage 语义（不经 TaskRunner），属于系统级恢复而非用户流转。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from argus_py.core.enums import TaskStatus
from argus_py.infra.queue import TaskQueue
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.client import WhiteboxClient, WhiteboxJobNotFoundError
from argus_py.whitebox.config import load_execution_config
from argus_py.whitebox.runner import _find_reusable_analysis_id, _persist_success_result

logger = logging.getLogger(__name__)

_REMOTE_QUERY_TIMEOUT = 15.0


def find_stale_whitebox_tasks(storage: TaskSQLiteStorage) -> list[dict]:
    """扫描租约过期的 WHITEBOX+RUNNING 任务。

    安全条件（与原 Worker reconciliation 一致）：
    1. status=RUNNING / task_type=WHITEBOX / external_job_id IS NOT NULL
    2. worker_lease_expires_at < now（租约已过期）
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    return storage.list_stale_whitebox_tasks(now_iso)


async def reconcile_orphan_whitebox_jobs(
    *,
    storage: TaskSQLiteStorage,
    lifecycle: TaskLifecycleService,
    queue: TaskQueue,
    client: WhiteboxClient,
) -> None:
    """启动恢复：逐条重新接管孤儿白盒作业。"""
    for row in find_stale_whitebox_tasks(storage):
        try:
            await _reconcile_one(storage, lifecycle, queue, client, row)
        except Exception:
            logger.exception("恢复孤儿白盒作业失败: task=%s", row["task_id"])


async def _reconcile_one(
    storage: TaskSQLiteStorage,
    lifecycle: TaskLifecycleService,
    queue: TaskQueue,
    client: WhiteboxClient,
    row: dict,
) -> None:
    task_id = row["task_id"]
    job_id = row["external_job_id"]
    remote = await _query_remote_status(client, job_id)
    logger.info(
        "启动恢复白盒任务: task=%s job=%s remote_status=%s",
        task_id,
        job_id,
        remote,
    )

    if remote == "SUCCEEDED":
        await _adopt_succeeded(storage, lifecycle, client, task_id, job_id)
    elif remote in ("PENDING", "RUNNING"):
        await _requeue_running(storage, lifecycle, queue, row, remote)
    elif remote == "TIMED_OUT":
        await _mark_terminal(
            lifecycle, row, TaskStatus.TIMEOUT, f"远端作业超时（启动恢复）: job={job_id}"
        )
    else:
        # CANCELLED / FAILED / EXPIRED / NO_JOB / UNREACHABLE
        await _mark_terminal(
            lifecycle,
            row,
            TaskStatus.FAILED,
            f"远端作业不可接管（启动恢复）: job={job_id} status={remote}",
        )


async def _query_remote_status(client: WhiteboxClient, job_id: str) -> str:
    if not job_id:
        return "NO_JOB"
    try:
        status = await client.get_analyze_job(job_id, timeout=_REMOTE_QUERY_TIMEOUT)
        return status.status
    except WhiteboxJobNotFoundError:
        return "EXPIRED"
    except Exception:
        logger.warning("启动恢复查询远端作业失败: job=%s", job_id, exc_info=True)
        return "UNREACHABLE"


async def _adopt_succeeded(
    storage: TaskSQLiteStorage,
    lifecycle: TaskLifecycleService,
    client: WhiteboxClient,
    task_id: str,
    job_id: str,
) -> None:
    """重新接管已完成结果：拉取结果 → 落 findings/投影 → COMPLETED。"""
    result = await client.get_analyze_job_result(job_id, timeout=_REMOTE_QUERY_TIMEOUT)
    task = storage.load(task_id)
    if task.status is not TaskStatus.RUNNING:
        logger.warning("跳过接管（任务已非 RUNNING）: task=%s", task_id)
        return
    analysis_id = _find_reusable_analysis_id(storage, task_id)
    if analysis_id is None:
        # 无可用 analysis_run（异常情况）：不冒险写入投影，任务留 RUNNING 由下轮恢复处理
        logger.warning("接管成功结果但无可用 analysis_run: task=%s job=%s", task_id, job_id)
        return
    scope = _resolve_scope(task)
    await _persist_success_result(
        lifecycle,
        task,
        result,
        analysis_id=analysis_id,
        source_root=None,
        scope=scope,
    )
    lifecycle.complete_task(task, result_summary=task.result_summary)
    logger.info("启动恢复接管成功结果: task=%s job=%s", task_id, job_id)


async def _requeue_running(
    storage: TaskSQLiteStorage,
    lifecycle: TaskLifecycleService,
    queue: TaskQueue,
    row: dict,
    remote: str,
) -> None:
    """重新接管运行中作业：任务重置 PENDING 并重新入队（幂等复用远端 job）。"""
    updated = storage.requeue_stale_task(
        row["task_id"],
        remote,
        expected_worker_id=row["w_id"],
        expected_lease=row["lease"],
    )
    if not updated:
        logger.info("重入队被跳过（已被并发修改）: task=%s", row["task_id"])
        return
    enqueue = await queue.try_enqueue(row["task_id"])
    logger.info("启动恢复重新入队: task=%s enqueue=%s", row["task_id"], enqueue.scheduler_status)


async def _mark_terminal(
    lifecycle: TaskLifecycleService,
    row: dict,
    target: TaskStatus,
    message: str,
) -> None:
    """CAS 标记终态（FAILED/TIMEOUT），防止与并发修改竞态。"""
    storage = lifecycle.storage
    now_iso = datetime.now(timezone.utc).isoformat()
    updated = storage.mark_stale_task_terminal(
        row["task_id"],
        target,
        now_iso,
        message,
        expected_worker_id=row["w_id"],
        expected_lease=row["lease"],
    )
    if not updated:
        logger.info("终态标记被跳过（已被并发修改）: task=%s", row["task_id"])
        return
    logger.warning(
        "启动恢复落终态: task=%s status=%s msg=%s", row["task_id"], target.value, message
    )


def _resolve_scope(task) -> str:
    """从任务配置解析 scope（复用 runner 配置恢复逻辑）。"""
    try:
        return load_execution_config(task).scope
    except Exception:
        logger.exception("解析任务 scope 失败: task=%s", task.task_id)
        return "all"
