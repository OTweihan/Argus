"""回归批次创建 / 取消 / 回收（可维护性 M3）。

async 路径需与 TaskQueue 交互；同步 SQLite/lifecycle 经 run_in_thread。
由 ``RegressionService`` 经 Mixin 组合；公开方法名与行为不变。
内部实现模块——请勿单独实例化。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Callable

from argus_py.core.constants import utc_now_iso
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.ids import generate_id
from argus_py.observability.context import run_in_thread
from argus_py.regression._common import (
    _ITEM_TERMINAL_STATUSES,
    _REGRESSION_NAME_PREFIX,
    REGRESSION_PARAMS_KEY,
    RegressionError,
    _BatchCreateInterrupted,
    _QueueFullAbort,
)
from argus_py.regression.enums import (
    RegressionItemStatus,
    RegressionRunStatus,
    RegressionTriggerSource,
)
from argus_py.regression.fingerprint import FINGERPRINT_VERSION
from argus_py.regression.models import CaseSnapshot, RegressionRun, RegressionRunItem

if TYPE_CHECKING:
    from argus_py.infra.queue import TaskQueue
    from argus_py.task.lifecycle import TaskLifecycleService
    from argus_py.task.storage import TaskSQLiteStorage

logger = logging.getLogger(__name__)


class RunCommandsMixin:
    """create_run / cancel_run 及创建期 fail-fast 回收。

    仅组合进 ``RegressionService``；依赖面见 ``_deps.RegressionServiceDeps``。
    """

    # 本 Mixin 实际使用的注入依赖
    _storage: TaskSQLiteStorage
    _lifecycle: TaskLifecycleService
    _queue: TaskQueue
    _publish: Callable[[str, str, dict[str, Any]], None]

    if TYPE_CHECKING:
        # 交叉方法由门面 ``RegressionService._require_run`` 提供（无运行时 stub）
        def _require_run(self, run_id: str) -> RegressionRun: ...

    async def create_run(
        self,
        project_id: str,
        trigger_source: str | RegressionTriggerSource = RegressionTriggerSource.API,
        triggered_by: str | None = None,
    ) -> RegressionRun:
        """创建并启动回归批次：快照化启用用例 → 逐条创建子任务并入队。"""
        source = RegressionTriggerSource(trigger_source)
        cases = await run_in_thread(
            self._storage.list_regression_cases,
            project_id,
            enabled_only=True,
        )
        if not cases:
            raise RegressionError(
                "REGRESSION_NO_ENABLED_CASES",
                f"项目 {project_id} 没有启用的回归用例。",
                details={"projectId": project_id},
            )
        baseline = await run_in_thread(self._storage.get_regression_baseline, project_id)
        now = utc_now_iso()
        run = RegressionRun(
            run_id=generate_id("regrun"),
            project_id=project_id,
            trigger_source=source,
            triggered_by=triggered_by,
            baseline_run_id=baseline.run_id if baseline else None,
            status=RegressionRunStatus.PENDING,
            created_at=now,
        )
        items: list[RegressionRunItem] = []
        for order, case in enumerate(cases):
            snapshot = CaseSnapshot.from_case(case)
            items.append(
                RegressionRunItem(
                    item_id=generate_id("regitem"),
                    run_id=run.run_id,
                    case_id=case.case_id,
                    case_name=case.name,
                    display_order=order,
                    case_snapshot_json=json.dumps(asdict(snapshot), ensure_ascii=False),
                    status=RegressionItemStatus.PENDING,
                    created_at=now,
                )
            )
        await run_in_thread(self._storage.create_regression_run_with_items, run, items)
        self._publish(
            "regression.batch.created",
            run.run_id,
            {"runId": run.run_id, "projectId": run.project_id, "itemTotal": len(items)},
        )

        # 单次 IO 线程内批量创建子任务 + 回填 item.task_id，避免 N 次 run_in_thread。
        # 入队仍在事件循环上逐个 try_enqueue（进程内队列 API 是 async）。
        # 创建后任意失败都要 fail-fast 收口批次，避免 PENDING 僵尸批次等到进程重启。
        # abort 回收范围 = 已成功创建的全部 pairs（不只是已 try_enqueue 的），
        # 避免「后半截已 attach 却标 SKIPPED、任务仍 PENDING」的孤儿。
        created_pairs: list[tuple[RegressionRunItem, str]] = []
        enqueued_count = 0
        try:
            created_pairs = await run_in_thread(self._create_item_tasks_batch, run, items)
            for _item, task_id in created_pairs:
                result = await self._queue.try_enqueue(task_id)
                if result.rejected:
                    raise _QueueFullAbort()
                enqueued_count += 1
        except _QueueFullAbort:
            await self._abort_create(
                run.run_id,
                items,
                created_pairs,
                error_code="REGRESSION_QUEUE_FULL",
                error_message=f"任务队列满载，仅 {enqueued_count} 个子任务进入执行。",
                item_error_code="BATCH_ABORTED_QUEUE_FULL",
                running_item_error_code="BATCH_ABORTED_TASK_RUNNING",
            )
            raise RegressionError(
                "TASK_QUEUE_FULL",
                "任务队列已满，回归批次已中止；请稍后重试。",
                http_status=503,
                details={"runId": run.run_id, "submitted": enqueued_count},
            )
        except _BatchCreateInterrupted as exc:
            logger.exception("回归批次创建子任务失败: run=%s", run.run_id)
            # 中途失败时 attach 尚未写入：先把已创建 pairs 回填到批次项，
            # 再走统一 abort，避免 UI/恢复路径看不到 task_id 的孤儿任务。
            if exc.pairs:
                try:
                    await run_in_thread(
                        self._storage.attach_regression_tasks,
                        [(item.item_id, task_id) for item, task_id in exc.pairs],
                    )
                except Exception:
                    logger.debug("回归批次失败回填 task_id 失败: run=%s", run.run_id, exc_info=True)
            await self._abort_create(
                run.run_id,
                items,
                list(exc.pairs),
                error_code="REGRESSION_CREATE_FAILED",
                error_message=f"批次创建中断：{exc.cause}",
                item_error_code="BATCH_ABORTED_CREATE_FAILED",
                running_item_error_code="BATCH_ABORTED_TASK_RUNNING",
            )
            raise RegressionError(
                "REGRESSION_CREATE_FAILED",
                "回归批次创建失败，已中止并回收已创建的子任务。",
                http_status=500,
                details={"runId": run.run_id, "submitted": len(exc.pairs)},
            ) from exc.cause
        except Exception as exc:
            logger.exception("回归批次创建失败: run=%s", run.run_id)
            await self._abort_create(
                run.run_id,
                items,
                created_pairs,
                error_code="REGRESSION_CREATE_FAILED",
                error_message=f"批次创建中断：{exc}",
                item_error_code="BATCH_ABORTED_CREATE_FAILED",
                running_item_error_code="BATCH_ABORTED_TASK_RUNNING",
            )
            raise RegressionError(
                "REGRESSION_CREATE_FAILED",
                "回归批次创建失败，已中止并回收已创建的子任务。",
                http_status=500,
                details={"runId": run.run_id, "submitted": len(created_pairs)},
            ) from exc

        await run_in_thread(self._storage.mark_regression_running, run.run_id)
        persisted = await run_in_thread(self._storage.get_regression_run, run.run_id)
        return persisted or run

    def _create_item_tasks_batch(
        self, run: RegressionRun, items: list[RegressionRunItem]
    ) -> list[tuple[RegressionRunItem, str]]:
        """同步批量创建子任务并回填关联（由 create_run 经 run_in_thread 调用一次）。

        中途失败时抛 ``_BatchCreateInterrupted``，携带已成功创建的 pairs 供 abort 回收；
        attach 仅在全部创建成功后统一写入。
        """
        pairs: list[tuple[RegressionRunItem, str]] = []
        attach_pairs: list[tuple[str, str]] = []
        try:
            for item in items:
                task = self._build_item_task(run, item)
                pairs.append((item, task.task_id))
                attach_pairs.append((item.item_id, task.task_id))
            self._storage.attach_regression_tasks(attach_pairs)
        except Exception as exc:
            raise _BatchCreateInterrupted(pairs, exc) from exc
        return pairs

    def _build_item_task(self, run: RegressionRun, item: RegressionRunItem) -> Any:
        """按批次项快照创建子任务（不单独 attach，由 batch 统一回填）。"""
        raw = json.loads(item.case_snapshot_json)
        snapshot = CaseSnapshot(
            case_id=item.case_id,
            name=item.case_name or str(raw.get("name") or ""),
            task_type=TaskType(raw.get("task_type", TaskType.BLACKBOX.value)),
            goal=str(raw.get("goal") or ""),
            start_url=raw.get("start_url"),
            max_steps=int(raw.get("max_steps", 0)),
            timeout_seconds=int(raw.get("timeout_seconds", 0)),
            capture_screenshots=bool(raw.get("capture_screenshots", True)),
            parameters=dict(raw.get("parameters") or {}),
            whitebox_config_json=raw.get("whitebox_config_json"),
        )
        parameters = {
            **snapshot.parameters,
            REGRESSION_PARAMS_KEY: {
                "runId": run.run_id,
                "itemId": item.item_id,
                "caseId": item.case_id,
            },
        }
        return self._lifecycle.create_task(
            goal=snapshot.goal,
            name=f"{_REGRESSION_NAME_PREFIX}{snapshot.name}",
            start_url=snapshot.start_url,
            task_type=snapshot.task_type,
            project_id=run.project_id,
            max_steps=max(1, snapshot.max_steps),
            timeout_seconds=max(1, snapshot.timeout_seconds),
            capture_screenshots=snapshot.capture_screenshots,
            parameters=parameters,
            whitebox_config_json=snapshot.whitebox_config_json,
        )

    def _create_item_task(self, run: RegressionRun, item: RegressionRunItem) -> Any:
        """兼容单条路径：创建子任务并立即回填关联。"""
        task = self._build_item_task(run, item)
        self._storage.attach_regression_task(item.item_id, task.task_id)
        return task

    async def _reclaim_submitted_tasks(
        self,
        submitted: list[tuple[Any, str]],
        *,
        running_item_error_code: str,
        cancelled_item_error_code: str,
        leave_running_tasks: bool,
    ) -> list[dict[str, Any]]:
        """批量回收已提交子任务并返回批次项状态更新列表。

        - 一次 ``snapshot_statuses`` + ``cancel_many``，避免 N 次队列锁往返；
        - 一次 ``load_task_headers`` 判断是否已终态，再仅对未终态任务
          ``cancel_task``（仍须逐任务落盘/发事件，但去掉 N 次全量 load）。
        - ``leave_running_tasks=True``（创建 fail-fast）：running 子任务保留跑完，
          批次项镜像为 cancelled 并注明仍在执行；
          ``False``（用户 cancel）：对 running 也发取消信号并尝试 cancel_task。

        创建 fail-fast 在 cancel 前会再读一次 live ``scheduler_status``：
        snapshot 为 queued 但 Worker 已取走的任务不得被误 cancel。
        """
        if not submitted:
            return []

        terminal_values = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.TIMEOUT.value,
            TaskStatus.CANCELLED.value,
        }
        status_snapshot = await self._queue.snapshot_statuses()
        queued_ids = [
            task_id for _, task_id in submitted if status_snapshot.get(task_id) == "queued"
        ]
        if queued_ids:
            await self._queue.cancel_many(queued_ids)

        # leave_running=False 时，对快照时已 running 的任务先打取消令牌，
        # 与原先 cancel_run 在 load 前 cancel token 的语义一致。
        # （snapshot→cancel 之间新升 running 的任务仍由下方 cancel_task 覆盖。）
        if not leave_running_tasks:
            for _, task_id in submitted:
                if status_snapshot.get(task_id) == "running":
                    try:
                        self._lifecycle.get_cancellation_token(task_id).cancel()
                    except Exception:
                        logger.debug("预取消 running 子任务令牌失败: %s", task_id, exc_info=True)

        task_ids = [task_id for _, task_id in submitted]
        headers = await run_in_thread(self._lifecycle.storage.load_task_headers, task_ids)

        item_updates: list[dict[str, Any]] = []
        for item, task_id in submitted:
            sched = status_snapshot.get(task_id)
            # 创建 fail-fast：快照已是 running → 保留跑完。
            if leave_running_tasks and sched == "running":
                item_updates.append(
                    self._running_item_mirror_update(item.item_id, running_item_error_code)
                )
                continue

            # 创建 fail-fast：快照为 queued/未知，但 cancel_many 后 Worker 已取走
            # → live 再确认，避免误 cancel 刚拉起的 running 任务。
            if leave_running_tasks and sched != "running":
                try:
                    live = await self._queue.scheduler_status(task_id)
                except Exception:
                    live = None
                    logger.debug("回收前 live 调度状态查询失败: %s", task_id, exc_info=True)
                if live == "running":
                    item_updates.append(
                        self._running_item_mirror_update(item.item_id, running_item_error_code)
                    )
                    continue

            try:
                header = headers.get(task_id)
                status_value = str(header["status"]) if header and "status" in header else None
                if status_value is None or status_value not in terminal_values:
                    await run_in_thread(self._lifecycle.cancel_task, task_id)
            except Exception:
                logger.debug("回归批次回收子任务失败: %s", task_id, exc_info=True)
            item_updates.append(
                {
                    "item_id": item.item_id,
                    "status": RegressionItemStatus.CANCELLED,
                    "error_code": cancelled_item_error_code,
                }
            )
        return item_updates

    @staticmethod
    def _running_item_mirror_update(item_id: str, error_code: str) -> dict[str, Any]:
        """创建 fail-fast：running 子任务保留执行时的批次项镜像。"""
        return {
            "item_id": item_id,
            "status": RegressionItemStatus.CANCELLED,
            "error_code": error_code,
            "error_message": "批次已中止，该子任务继续执行至结束（结果不计入本批次）。",
        }

    async def _abort_create(
        self,
        run_id: str,
        items: list[RegressionRunItem],
        submitted: list[tuple[RegressionRunItem, str]],
        *,
        error_code: str,
        error_message: str,
        item_error_code: str,
        running_item_error_code: str = "BATCH_ABORTED_TASK_RUNNING",
    ) -> None:
        """创建阶段 fail-fast：批次先落 FAILED（阻断终态回调路径），再回收子任务。

        顺序很关键：若先取消子任务，其终态回调会在批次仍为 pending 时触发
        正常 finalize（COMPLETED），与失败语义竞态。先 CAS 占住终态后，回调
        自动忽略；批次项状态在此显式镜像。

        ``submitted`` 为已成功创建（可能已 attach / 已入队）的 (item, task_id)；
        其余 items 标 SKIPPED。
        """
        submitted_ids = {task_id for _, task_id in submitted}
        submitted_items = {item.item_id for item, _ in submitted}
        await run_in_thread(
            self._storage.finalize_regression_run,
            run_id=run_id,
            status=RegressionRunStatus.FAILED,
            gate_result=None,
            summary_json=json.dumps({"fingerprintVersion": FINGERPRINT_VERSION}),
            error_code=error_code,
            error_message=error_message,
        )
        self._publish(
            "regression.batch.finalized",
            run_id,
            {"runId": run_id, "status": RegressionRunStatus.FAILED.value},
        )

        # 已入队未执行的子任务移出队列并取消；已在执行的保留跑完（结果仍在
        # 任务列表可见）。调度快照 + 批量 cancel/headers，避免 N 次队列/SQLite 往返。
        item_updates: list[dict[str, Any]] = []
        for item in items:
            if item.item_id not in submitted_items:
                item_updates.append(
                    {
                        "item_id": item.item_id,
                        "status": RegressionItemStatus.SKIPPED,
                        "error_code": item_error_code,
                    }
                )

        recovered = await self._reclaim_submitted_tasks(
            submitted,
            running_item_error_code=running_item_error_code,
            cancelled_item_error_code=item_error_code,
            leave_running_tasks=True,
        )
        item_updates.extend(recovered)
        if item_updates:
            await run_in_thread(self._storage.update_regression_item_statuses, item_updates)
        # 防御：submitted_ids 仅用于可观测性日志，避免未使用告警
        if submitted_ids:
            logger.debug(
                "回归批次创建中止: run=%s error=%s submitted=%d",
                run_id,
                error_code,
                len(submitted_ids),
            )

    async def cancel_run(self, run_id: str) -> RegressionRun:
        """取消未完成批次：CAS 置 cancelled 后尽力取消全部未终态子任务。"""
        run = await run_in_thread(self._require_run, run_id)
        if run.status not in (RegressionRunStatus.PENDING, RegressionRunStatus.RUNNING):
            raise RegressionError(
                "REGRESSION_RUN_NOT_RUNNING",
                f"只有未完成的批次可以取消，当前状态：{run.status.value}。",
                http_status=409,
                details={"runId": run_id, "status": run.status.value},
            )
        ok = await run_in_thread(
            self._storage.finalize_regression_run,
            run_id=run_id,
            status=RegressionRunStatus.CANCELLED,
            gate_result=None,
            summary_json=run.summary_json or "{}",
            error_code="REGRESSION_CANCELLED",
            error_message="用户取消批次。",
        )
        if not ok:
            raise RegressionError(
                "REGRESSION_RUN_NOT_RUNNING",
                "批次已被并发操作收尾，无法取消。",
                http_status=409,
                details={"runId": run_id},
            )

        items = await run_in_thread(self._storage.get_regression_items, run_id)
        item_updates: list[dict[str, Any]] = []
        submitted: list[tuple[Any, str]] = []
        for item in items:
            if item.status in _ITEM_TERMINAL_STATUSES:
                continue
            if item.task_id is None:
                item_updates.append(
                    {
                        "item_id": item.item_id,
                        "status": RegressionItemStatus.SKIPPED,
                        "error_code": "BATCH_CANCELLED",
                    }
                )
                continue
            submitted.append((item, item.task_id))
        # 用户取消：排队与运行中的子任务都要信号取消（与创建 fail-fast 不同，
        # 创建 fail-fast 允许已 running 的任务跑完）。
        recovered = await self._reclaim_submitted_tasks(
            submitted,
            running_item_error_code="BATCH_CANCELLED",
            cancelled_item_error_code="BATCH_CANCELLED",
            leave_running_tasks=False,
        )
        item_updates.extend(recovered)
        if item_updates:
            await run_in_thread(self._storage.update_regression_item_statuses, item_updates)
        self._publish(
            "regression.batch.finalized",
            run_id,
            {"runId": run_id, "status": RegressionRunStatus.CANCELLED.value},
        )
        return await run_in_thread(self._require_run, run_id)
