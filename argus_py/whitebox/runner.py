"""白盒任务执行器。

编排：配置恢复 → SourceResolver → 可见性校验 → 异步作业提交/轮询 →
结果获取 → Findings 映射 → 结构化投影。

异常通过类型化 ``WhiteboxTaskError`` 子类表达，由 ``TaskRunner``
统一映射为任务终态。

实现拆分（可维护性 M4，行为不变）：

- ``job_poll.JobPollMixin``：``_poll`` / 远端取消确认 / best-effort cancel
- ``result_persist``：成功结果落盘、analysis_id 复用、诊断摘要
- 本模块：门面组合 + ``run`` 主流程 + 源码/可见性/提交/时间线

风格与 M3 一致：Mixin + 门面注入依赖；交叉方法仅 TYPE_CHECKING 声明。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from argus_py.analysis.enums import AnalysisRunStatus
from argus_py.core.constants import utc_now
from argus_py.observability.context import run_in_thread
from argus_py.task.event import TaskTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Task
from argus_py.whitebox.client import (
    VisibilityStatus,
    WhiteboxClient,
    WhiteboxResultNotReadyError,
)
from argus_py.whitebox.config import (
    ExecutionWhiteboxConfig,
    SourceType,
    load_persisted_config,
)
from argus_py.whitebox.exceptions import (
    WhiteboxSourceResolutionError,
    WhiteboxTaskCancelled,
    WhiteboxTaskTimeout,
    WhiteboxVisibilityError,
)
from argus_py.whitebox.job_poll import JobPollMixin
from argus_py.whitebox.models import WhiteboxResult
from argus_py.whitebox.result_persist import (
    find_reusable_analysis_id,
    persist_success_result,
)
from argus_py.whitebox.source_resolver import (
    ResolvedSource,
    SourceResolutionError,
    SourceResolver,
)

logger = logging.getLogger(__name__)

__all__ = [
    "WhiteboxRunner",
]


class WhiteboxRunner(JobPollMixin):
    """白盒分析任务执行器。

    编排：SourceResolver → WhiteboxClient 异步作业 → 写 Findings/产物。
    """

    def __init__(
        self,
        *,
        client: WhiteboxClient,
        source_resolver: SourceResolver | None = None,
        timeline_service: TaskTimelineService,
        lifecycle: TaskLifecycleService,
        poll_interval: float = 5.0,
        max_poll_interval: float = 10.0,
        cancel_confirmation_timeout: float = 5.0,
        on_analysis_succeeded: Callable[[str, str], Any] | None = None,
    ) -> None:
        self._client = client
        self._source_resolver = source_resolver or SourceResolver()
        self._timeline = timeline_service
        self._lifecycle = lifecycle
        self._poll_interval = poll_interval
        self._max_poll_interval = max_poll_interval
        # 本地取消后等待 Java 确认落 CANCELLED 的最大时长（O-04）；超窗视为
        # “未确认”，保留 STOPPED_WAITING 语义。
        self._cancel_confirmation_timeout = max(0.0, cancel_confirmation_timeout)
        self._on_analysis_succeeded = on_analysis_succeeded

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def run(self, task: Task) -> None:
        """执行白盒分析任务。

        不返回 Task——完成时直接修改 task 对象；终态由 TaskRunner 写入。
        异常通过 ``WhiteboxTaskError`` 子类表达。
        """
        # 0. 恢复配置（新 JSON 快照优先，回退旧 parameters；与 recovery 共用）
        persisted = load_persisted_config(task)
        exec_config = persisted.to_execution_config()
        source_repo_url = persisted.source_repo_url

        # 0.5 分配/复用 analysis_id（O-04 启动恢复后重新接管同一 run，
        # 非终态 run 的 analysis_id 复用，终态则新建）
        reused_run_id = self._reusable_analysis_id(task.task_id)
        analysis_id = reused_run_id or uuid4().hex

        # 1. 统一 deadline
        deadline = time.monotonic() + task.timeout_seconds
        resolved: ResolvedSource | None = None
        remote_may_be_running = False

        try:
            # 2. 源码解析 + 立即持久化快照
            resolved = await self._resolve_source(exec_config, task.task_id, deadline)
            self._write_snapshot(task, resolved, source_repo_url)
            await run_in_thread(self._lifecycle.save_task, task)
            await self._safe_emit(
                "whitebox_source_resolved",
                task.task_id,
                data={
                    "source_type": resolved.source_type,
                    "commit_sha": resolved.resolved_commit_sha,
                    "content_sha256": resolved.content_sha256,
                    "requested_ref": resolved.requested_ref,
                    "ref_type": resolved.ref_type,
                    "dirty": resolved.is_dirty,
                    "source_revision": resolved.source_revision,
                    "snapshot_digest": resolved.snapshot_digest,
                },
            )

            # 2.5 创建/复位 AnalysisRun（源码快照已就绪）
            # 复用非终态 run（启动恢复重新接管）时复位而非重复插入；
            # 全新执行才创建。
            if reused_run_id is not None:
                await run_in_thread(self._lifecycle.reset_analysis_run, analysis_id)
            else:
                await run_in_thread(
                    self._lifecycle.create_analysis_run,
                    analysis_id=analysis_id,
                    task_id=task.task_id,
                    # 快照标识语义统一：local 源优先内容哈希（能捕获脏工作区），
                    # git 源使用克隆 HEAD commit SHA（跨运行稳定），两者皆无时以 analysis_id 兜底。
                    source_snapshot_id=(
                        resolved.content_sha256 or resolved.resolved_commit_sha or analysis_id
                    ),
                    resolved_commit_sha=resolved.resolved_commit_sha,
                    result_schema_version=1,
                    config_json=task.whitebox_config_json or "{}",
                )

            # 3. 可见性校验
            await self._check_visibility(
                resolved.resolved_path,
                task.task_id,
                deadline,
            )

            # 4. 提交 + 持久化 job_id
            # 从发起 POST 开始就必须假定远端可能已接收；
            # 即使本地超时没拿到 job_id，也不能立即删除快照。
            remote_may_be_running = True
            job_id = await self._submit_job(task, resolved, exec_config)
            await self._safe_emit(
                "whitebox_submitted",
                task.task_id,
                data={"jobId": job_id},
            )
            await run_in_thread(
                self._lifecycle.start_analysis_run,
                analysis_id,
            )

            # 5. 轮询（Worker shutdown 触发 asyncio.CancelledError 时 best-effort 通知远端）
            try:
                await self._poll(task, job_id, deadline)
            except asyncio.CancelledError:
                await asyncio.shield(self._best_effort_cancel(task, job_id))
                raise
            remote_may_be_running = False

            # 6. 获取结果（含 409 重试）
            result = await self._get_result_with_retry(job_id, deadline)
            await persist_success_result(
                self._lifecycle,
                task,
                result,
                analysis_id=analysis_id,
                source_root=resolved.resolved_path,
                scope=exec_config.scope,
            )
            endpoint_count = len(result.endpoints)
            finding_count = len(result.findings)

            # ── 关联唤醒：通知等待中的 CorrelationRun ──
            if self._on_analysis_succeeded is not None:
                try:
                    maybe_coro = self._on_analysis_succeeded(task.task_id, analysis_id)
                    if maybe_coro is not None:
                        await maybe_coro
                except Exception:
                    logger.warning(
                        "关联唤醒回调失败: task_id=%s analysis_id=%s",
                        task.task_id,
                        analysis_id,
                        exc_info=True,
                    )

            await self._safe_emit_terminal(
                "whitebox_succeeded",
                task.task_id,
                summary=(
                    f"分析完成: {endpoint_count} 端点, "
                    f"{finding_count} 问题, "
                    f"{len(result.call_graph.nodes)} 调用图节点"
                ),
            )

            logger.info(
                "白盒分析完成: endpoints=%d callgraph_nodes=%d findings=%d flows=%d clusters=%d",
                endpoint_count,
                len(result.call_graph.nodes),
                finding_count,
                len(result.execution_flows),
                len(result.clusters),
            )

        except WhiteboxTaskCancelled as exc:
            await self._safe_emit_terminal(
                "whitebox_cancelled",
                task.task_id,
                summary=str(exc),
                data={
                    "jobId": exc.job_id,
                    "origin": exc.origin,
                    "errorCode": exc.error_code,
                },
            )
            # 取消终态按 origin 分派：本地取消 = 我们只停止等待，远端作业可能仍在运行；
            # 远端确认取消（Java 状态机暂不产出，防御性）才落 CANCELLED。
            run_status = (
                AnalysisRunStatus.CANCELLED
                if exc.origin == "remote"
                else AnalysisRunStatus.STOPPED_WAITING
            )
            await run_in_thread(
                self._lifecycle.mark_analysis_terminal,
                analysis_id,
                run_status,
                exc.error_code or "TASK_CANCELLED",
                str(exc),
            )
            raise
        except WhiteboxTaskTimeout as exc:
            await self._safe_emit_terminal(
                "whitebox_timed_out",
                task.task_id,
                summary=str(exc),
                data={
                    "jobId": exc.job_id,
                    "errorCode": exc.error_code,
                },
            )
            await run_in_thread(
                self._lifecycle.mark_analysis_terminal,
                analysis_id,
                AnalysisRunStatus.TIMED_OUT,
                exc.error_code or "TASK_TIMEOUT",
                str(exc),
            )
            raise
        except Exception as exc:
            error_data: dict[str, object] = {}
            if hasattr(exc, "error_code") and exc.error_code:
                error_data["errorCode"] = exc.error_code
            await self._safe_emit_terminal(
                "whitebox_failed",
                task.task_id,
                summary=str(exc),
                data=error_data,
            )
            await run_in_thread(
                self._lifecycle.mark_analysis_failed,
                analysis_id,
                getattr(exc, "error_code", None) or "ANALYSIS_FAILED",
                str(exc),
            )
            raise
        finally:
            await self._safe_flush()
            if resolved is not None and (
                not remote_may_be_running
                or task.external_job_status
                in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "EXPIRED"}
            ):
                try:
                    await run_in_thread(self._source_resolver.release, resolved)
                except Exception:
                    logger.exception("清理白盒源码快照失败: %s", resolved.resolved_path)
            elif resolved is not None and remote_may_be_running:
                logger.info(
                    "保留白盒源码快照（远端状态不确定，由 24h TTL 回收）: %s remote_status=%s",
                    resolved.resolved_path,
                    task.external_job_status,
                )

    # ── 源码解析 ──────────────────────────────────────────────────────────────

    async def _resolve_source(
        self,
        config: ExecutionWhiteboxConfig,
        task_id: str,
        deadline: float,
    ) -> ResolvedSource:
        """解析源码，剩余时间超过 10s 才开始克隆。"""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WhiteboxTaskTimeout(
                job_id="",
                deadline=0,
            )
        try:
            if config.source_type == SourceType.GIT:
                return await run_in_thread(
                    self._source_resolver.resolve,
                    config.repo_url,
                    config.ref,
                    clone_id=task_id,
                )
            return await run_in_thread(
                self._source_resolver.resolve_path,
                config.source_path,
                snapshot_id=task_id,
            )
        except SourceResolutionError as exc:
            raise WhiteboxSourceResolutionError(str(exc)) from exc

    def _write_snapshot(
        self,
        task: Task,
        resolved: ResolvedSource,
        source_repo_url: str | None,
    ) -> None:
        """将源码快照写入 task（不持久化——调用方负责 save）。"""
        task.source_type = resolved.source_type
        task.source_repo_url = source_repo_url
        task.source_requested_ref = resolved.requested_ref
        task.source_resolved_commit_sha = resolved.resolved_commit_sha
        task.source_ref_type = resolved.ref_type
        task.source_dirty = resolved.is_dirty

    # ── 可见性校验 ────────────────────────────────────────────────────────────

    async def _check_visibility(
        self,
        resolved_path: str,
        task_id: str,
        deadline: float,
    ) -> None:
        """验证 Python 和 Java 均能访问源码路径。"""
        local_path = Path(resolved_path)
        if not local_path.is_dir():
            raise WhiteboxVisibilityError(f"源码路径不存在: {resolved_path}")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WhiteboxTaskTimeout(job_id="", deadline=0)

        visibility = await self._client.validate_source(resolved_path)

        if visibility.status is VisibilityStatus.ENDPOINT_UNSUPPORTED:
            raise WhiteboxVisibilityError(
                f"Java 不支持 validate-source 端点，"
                f"请升级 Java 分析器或确认版本兼容。"
                f"（原因: {visibility.reason}）"
            )
        if visibility.status is VisibilityStatus.ANALYZER_UNAVAILABLE:
            raise WhiteboxVisibilityError(
                f"Java 分析器不可达，无法完成跨进程可见性校验。（原因: {visibility.reason}）"
            )
        if visibility.status is not VisibilityStatus.VALIDATED:
            raise WhiteboxVisibilityError(visibility.reason or "可见性校验失败")
        if not visibility.readable:
            raise WhiteboxVisibilityError(
                f"Java 无法读取源码路径: {resolved_path}。"
                f"容器部署请确保 Python 与 Java 使用共享卷挂载同一路径。"
            )
        if visibility.allowed is False:
            raise WhiteboxVisibilityError(
                f"Java 拒绝分析该路径（不在允许的源码根目录内）: {resolved_path}。"
                f"请将源码放入共享源码目录（如 /tmp/sources）。"
            )
        # 校验成功
        await self._safe_emit(
            "whitebox_source_validated",
            task_id,
            data={"validated": True},
        )

    # ── 提交作业 ──────────────────────────────────────────────────────────────

    def _reusable_analysis_id(self, task_id: str) -> str | None:
        """返回任务最近的非终态 analysis_run 的 analysis_id（O-04 重新接管）。

        RUNNING 的 worker 崩溃重启后，恢复路径把任务重置为 PENDING 重新入队，
        这里复用原 run 的 analysis_id，让同一分析记录继续完成而非重复插入。
        """
        return find_reusable_analysis_id(self._lifecycle.storage, task_id)

    async def _submit_job(
        self,
        task: Task,
        resolved: ResolvedSource,
        config: ExecutionWhiteboxConfig,
    ) -> str:
        """提交异步分析作业并立即持久化 job_id。"""
        job_status = await self._client.submit_analyze_job(
            source_path=resolved.resolved_path,
            scope=config.scope,
            maven=config.maven.model_dump(exclude_none=True, by_alias=True)
            if config.maven
            else None,
            target_modules=config.target_modules or None,
            client_request_id=f"{task.task_id}:{task.execution_attempt}",
            timeout_seconds=max(1, int(task.timeout_seconds)),
            # O-07：把 Python 在物化快照时算好的稳定 revision 传给 Java，
            # 让 Java 缓存键免去每次查找时的全量源码树哈希。
            source_revision=resolved.source_revision,
            snapshot_digest=resolved.snapshot_digest,
        )
        job_id = job_status.job_id
        task.external_job_id = job_id
        task.external_job_status = job_status.status
        task.external_job_submitted_at = utc_now().isoformat()
        await run_in_thread(self._lifecycle.save_task, task)
        logger.info("白盒分析作业已提交: job_id=%s task=%s", job_id, task.task_id)
        return job_id

    # ── 获取结果 ──────────────────────────────────────────────────────────────

    async def _get_result_with_retry(
        self,
        job_id: str,
        deadline: float,
    ) -> WhiteboxResult:
        """获取结果，409 在 deadline 内重试。"""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WhiteboxTaskTimeout(
                    job_id=job_id,
                    deadline=0,
                )

            request_timeout = min(
                self._client.request_timeout,
                max(remaining, 0.5),
            )

            try:
                return await self._client.get_analyze_job_result(
                    job_id,
                    timeout=request_timeout,
                )
            except WhiteboxResultNotReadyError:
                await asyncio.sleep(min(1.0, remaining))

    # ── 时间线安全封装 ────────────────────────────────────────────────────────

    async def _safe_emit(self, event_type: str, task_id: str, **kwargs: Any) -> None:
        """发送时间线事件（best-effort，失败不覆盖业务异常）。"""
        try:
            await self._timeline.emit(task_id, event_type, phase="whitebox", **kwargs)
        except Exception:
            logger.exception("时间线事件写入失败: %s", event_type)

    async def _safe_emit_terminal(self, event_type: str, task_id: str, **kwargs: Any) -> None:
        """发送终态事件并立即 flush（best-effort）。"""
        try:
            await self._timeline.emit(task_id, event_type, phase="whitebox", **kwargs)
            await self._timeline.flush_events()
        except Exception:
            logger.exception("时间线终态事件写入失败: %s", event_type)

    async def _safe_flush(self) -> None:
        """flush 时间线缓冲区（best-effort）。"""
        try:
            await self._timeline.flush_events()
        except Exception:
            logger.exception("时间线 flush 失败")
