"""白盒远端作业轮询与取消确认（可维护性 M4）。

由 ``WhiteboxRunner`` 经 Mixin 组合；公开入口仍是 ``WhiteboxRunner.run``。
取消确认超时语义（O-04）不变：

- ``confirmed``：Java 已落 CANCELLED → origin=remote
- ``terminal``：远端已是其它终态 → 交常规状态映射
- ``requested`` / ``unknown`` / ``unreachable`` → origin=local（STOPPED_WAITING）

内部实现模块——请勿单独实例化 Mixin。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from argus_py.core.constants import utc_now
from argus_py.core.enums import TaskStatus
from argus_py.observability.context import run_in_thread
from argus_py.whitebox.client import (
    WhiteboxJobNotFoundError,
    WhiteboxPermanentError,
    WhiteboxTransientError,
)
from argus_py.whitebox.exceptions import (
    WhiteboxRemoteJobFailed,
    WhiteboxTaskCancelled,
    WhiteboxTaskError,
    WhiteboxTaskTimeout,
)

if TYPE_CHECKING:
    from argus_py.task.lifecycle import TaskLifecycleService
    from argus_py.task.models import Task
    from argus_py.whitebox.client import WhiteboxClient

logger = logging.getLogger(__name__)


class JobPollMixin:
    """``_poll`` / 远端取消确认 / best-effort cancel。

    仅组合进 ``WhiteboxRunner``；请勿单独实例化。

    依赖面（由门面 ``__init__`` 注入）：

    - ``_client`` / ``_lifecycle``
    - ``_poll_interval`` / ``_max_poll_interval`` / ``_cancel_confirmation_timeout``
    - 交叉方法 ``_safe_emit``（门面提供，仅 TYPE_CHECKING 声明）
    """

    _client: WhiteboxClient
    _lifecycle: TaskLifecycleService
    _poll_interval: float
    _max_poll_interval: float
    _cancel_confirmation_timeout: float

    if TYPE_CHECKING:
        # 交叉方法由门面 ``WhiteboxRunner`` 提供（无运行时 stub）
        async def _safe_emit(self, event_type: str, task_id: str, **kwargs: Any) -> None: ...

    async def _poll(
        self,
        task: Task,
        job_id: str,
        baseline_deadline: float,
    ) -> None:
        """轮询 Java 作业状态直到终态。

        O-04：本地取消先 best-effort 请求远端协作取消；Java 确认落 CANCELLED
        才以 origin="remote" 结束（analysis_runs 落 CANCELLED），无法确认时保留
        origin="local"（STOPPED_WAITING）。超时同样先通知远端再抛超时。
        """
        last_sequence = -1
        seen_event_ids: set[str] = set()
        consecutive_errors = 0
        cancel_handled = False

        while True:
            # 取消检查
            token = self._lifecycle.get_cancellation_token(task.task_id)
            if token.is_cancelled and not cancel_handled:
                cancel_handled = True
                outcome = await self._cancel_remote_with_confirmation(task, job_id)
                if outcome == "confirmed":
                    task.external_job_status = "CANCELLED"
                    logger.info("任务 %s 取消已获远端确认: job=%s", task.task_id, job_id)
                    raise WhiteboxTaskCancelled(job_id=job_id, origin="remote")
                if outcome == "unreachable":
                    logger.warning(
                        "任务 %s 已取消，但无法联系远端取消作业 %s（远端作业可能仍在运行）",
                        task.task_id,
                        job_id,
                    )
                    raise WhiteboxTaskCancelled(job_id=job_id, origin="local")
                if outcome in ("requested", "unknown"):
                    logger.warning(
                        "任务 %s 已取消，远端未在确认窗口内确认取消 job=%s（保留 STOPPED_WAITING）",
                        task.task_id,
                        job_id,
                    )
                    raise WhiteboxTaskCancelled(job_id=job_id, origin="local")
                # outcome == "terminal"：远端已被我们或并发置为终态，
                # 落入下方常规状态映射统一处理（SUCCEEDED→成功 / TIMED_OUT→超时等）。

            remaining = baseline_deadline - time.monotonic()
            if remaining <= 0:
                await self._best_effort_cancel(task, job_id)
                raise WhiteboxTaskTimeout(
                    job_id=job_id,
                    deadline=task.timeout_seconds,
                )

            # 动态 request timeout（不超过剩余时间）
            request_timeout = min(
                self._client.request_timeout,
                max(remaining, 0.5),
            )

            try:
                job_status = await self._client.get_analyze_job(
                    job_id,
                    timeout=request_timeout,
                )
                consecutive_errors = 0
            except WhiteboxTransientError as exc:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise WhiteboxTaskError(f"连续 {consecutive_errors} 次轮询瞬时失败") from exc
                delay = min(2**consecutive_errors, self._max_poll_interval)
                # sleep 不超过剩余时间
                await asyncio.sleep(min(delay, max(remaining, 0)))
                continue
            except WhiteboxJobNotFoundError as exc:
                raise WhiteboxTaskError(f"远端作业 {job_id} 不存在，可能已过期") from exc
            except WhiteboxPermanentError:
                raise

            # 窄字段更新（不覆盖并发终态）
            task.external_job_status = job_status.status
            task.external_job_last_polled_at = utc_now().isoformat()
            await run_in_thread(
                self._lifecycle.storage.update_external_job_checkpoint,
                task.task_id,
                external_job_status=job_status.status,
                external_job_last_polled_at=task.external_job_last_polled_at,
                expected_status=TaskStatus.RUNNING.value,
            )

            # 事件去重（按 sequence + eventId；兼容旧版无此字段的 Java）
            for evt in sorted(job_status.events, key=lambda e: e.sequence):
                if evt.event_id and evt.event_id in seen_event_ids:
                    continue
                # 仅当 sequence >= 0 且未超过去重窗口时才跳过
                if evt.sequence >= 0 and evt.sequence <= last_sequence:
                    continue
                if evt.sequence >= 0 and evt.sequence > last_sequence + 1:
                    logger.debug(
                        "事件 sequence 缺口: %d→%d",
                        last_sequence,
                        evt.sequence,
                    )
                if evt.event_id:
                    seen_event_ids.add(evt.event_id)
                if evt.sequence >= 0:
                    last_sequence = evt.sequence
                await self._safe_emit(
                    "whitebox_progress",
                    task.task_id,
                    summary=evt.message,
                    data={
                        "stage": evt.stage,
                        "level": evt.level,
                        "sequence": evt.sequence,
                        "eventId": evt.event_id,
                    },
                )

            # 终态判断（映射表）
            status = job_status.status
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                raise WhiteboxRemoteJobFailed(
                    job_id=job_id,
                    error=job_status.error,
                )
            if status == "CANCELLED":
                raise WhiteboxTaskCancelled(
                    job_id=job_id,
                    origin="remote",
                )
            if status == "TIMED_OUT":
                raise WhiteboxTaskTimeout(
                    job_id=job_id,
                    deadline=task.timeout_seconds,
                )
            if status == "EXPIRED":
                raise WhiteboxRemoteJobFailed(
                    job_id=job_id,
                    error="远端作业已过期",
                )
            if status in ("PENDING", "RUNNING"):
                await asyncio.sleep(min(self._poll_interval, max(remaining, 0)))
                continue
            # 未知状态 → 协议失败
            raise WhiteboxTaskError(f"未知作业状态: {status}")

    async def _best_effort_cancel(self, task: Task, job_id: str) -> None:
        """best-effort 请求远端取消；失败仅告警，不覆盖业务异常。

        返回终态时同步 task.external_job_status，供 finally 快照清理决策。
        """
        if not job_id:
            return
        try:
            status = await self._client.cancel_analyze_job(job_id)
            if status is not None and status.status in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "EXPIRED",
            }:
                task.external_job_status = status.status
        except Exception:
            logger.warning(
                "best-effort 取消远端作业失败: task=%s job=%s",
                task.task_id,
                job_id,
                exc_info=True,
            )

    async def _cancel_remote_with_confirmation(
        self,
        task: Task,
        job_id: str,
    ) -> str:
        """请求远端取消并在确认窗口内等待 Java 落 CANCELLED。

        Returns
        -------
        str
            - ``"confirmed"``：Java 已确认落 CANCELLED
            - ``"terminal"``：作业已是 SUCCEEDED/FAILED/TIMED_OUT/EXPIRED（交轮询处理）
            - ``"requested"``：取消已请求但窗口内未确认（→ STOPPED_WAITING）
            - ``"unknown"``：作业不存在/旧版 Java 无端点（404）
            - ``"unreachable"``：无法联系远端
        """
        try:
            status = await self._client.cancel_analyze_job(job_id)
        except Exception:
            logger.warning("请求远端取消失败: task=%s job=%s", task.task_id, job_id, exc_info=True)
            return "unreachable"

        if status is None:
            # 404：作业已过期或旧版 Java 无此端点——不能据此判定已取消
            return "unknown"
        if status.status == "CANCELLED":
            return "confirmed"
        if status.status in {"SUCCEEDED", "FAILED", "TIMED_OUT", "EXPIRED"}:
            # 取消与完成并发：远端已先置终态，交由常规状态映射处理
            return "terminal"

        # RUNNING/PENDING：在确认窗口内轮询 GET，等 Java 工作线程自省落 CANCELLED
        window_deadline = time.monotonic() + self._cancel_confirmation_timeout
        while time.monotonic() < window_deadline:
            remaining = window_deadline - time.monotonic()
            try:
                polled = await self._client.get_analyze_job(
                    job_id,
                    timeout=min(self._client.request_timeout, max(remaining, 0.5)),
                )
            except Exception:
                logger.warning(
                    "取消确认窗口内查询远端作业失败: task=%s job=%s",
                    task.task_id,
                    job_id,
                    exc_info=True,
                )
                return "requested"
            if polled.status == "CANCELLED":
                return "confirmed"
            if polled.status in {"SUCCEEDED", "FAILED", "TIMED_OUT", "EXPIRED"}:
                return "terminal"
            await asyncio.sleep(min(0.5, max(remaining, 0)))
        return "requested"
