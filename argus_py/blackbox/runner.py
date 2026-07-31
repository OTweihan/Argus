"""黑盒 Agent 执行器（门面）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from argus_py.blackbox.action_executor import ActionExecutor
from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.events import BlackboxEvents
from argus_py.blackbox.evidence import EvidenceCollector
from argus_py.blackbox.execution_loop import BlackboxExecutionLoop
from argus_py.blackbox.finalizer import Finalizer
from argus_py.blackbox.llm_boundary import LLMBoundaryFactory
from argus_py.blackbox.models import BlackboxTaskInput
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.blackbox.recovery import RecoveryPolicy
from argus_py.browser import BrowserSession
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.core.paths import SCREENSHOTS_DIR
from argus_py.correlation.enums import (
    BlackboxRunStatus,
)
from argus_py.correlation.models import (
    _CapturedRequest,
)
from argus_py.correlation.path_utils import extract_origin
from argus_py.observability.context import bind_context
from argus_py.report.generator import ReportGenerator
from argus_py.task.event import TaskTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task
from argus_py.task.read import TaskReadService

logger = logging.getLogger(__name__)

BrowserSessionFactory = Callable[[Task], BrowserSession]


class BlackboxRunner:
    """串联规划、浏览器和评估的黑盒 Agent 执行器（门面，委托子组件）。"""

    def __init__(
        self,
        lifecycle: TaskLifecycleService,
        reader: TaskReadService,
        log_service: TaskLogService,
        timeline_service: TaskTimelineService,
        planner: BlackboxPlanner | None = None,
        evaluator: BlackboxEvaluator | None = None,
        browser_session_factory: BrowserSessionFactory | None = None,
        report_generator: ReportGenerator | None = None,
        max_plan_steps: int = 3,
        max_recovery_attempts: int = 2,
        model_config_service: ModelConfigService | None = None,
        # ── 关联集成（可选）──
        persist_request_batch: Callable[[list[dict[str, Any]]], Any] | None = None,
        create_blackbox_run: Callable[[Task], str] | None = None,
        create_correlation_run: Callable[[str, Task], dict[str, Any] | None] | None = None,
        finalize_blackbox_run: Callable[[str, str, Any], Any] | None = None,
        claim_and_execute_correlation: Callable[[str, str], Any] | None = None,
        worker_id: str = "",
    ) -> None:
        self._lifecycle = lifecycle
        self._reader = reader
        self._log = log_service
        self._timeline = timeline_service
        self.planner = planner or BlackboxPlanner()
        self.evaluator = evaluator or BlackboxEvaluator()
        self.browser_session_factory = browser_session_factory or self._default_browser_session
        self.max_plan_steps = max_plan_steps
        self._model_config_service = model_config_service

        self.evidence = EvidenceCollector()
        self.action_executor = ActionExecutor(log_service, self.evidence)
        self.finalizer = Finalizer(log_service, lifecycle, reader, report_generator)
        self.events = BlackboxEvents(timeline_service, log_service)
        self.recovery_policy = RecoveryPolicy(max_attempts=max_recovery_attempts)
        self.llm_boundary = LLMBoundaryFactory(
            default_planner=None if planner is None else planner,
            default_evaluator=None if evaluator is None else evaluator,
            model_config_service=model_config_service,
        )

        # ── 关联集成回调 ──
        self._persist_request_batch = persist_request_batch
        self._create_blackbox_run_fn = create_blackbox_run
        self._create_correlation_run_fn = create_correlation_run
        self._finalize_blackbox_run_fn = finalize_blackbox_run
        self._claim_and_execute_correlation_fn = claim_and_execute_correlation
        self._worker_id = worker_id

    async def run(self, task: Task | BlackboxTaskInput) -> Task:
        """执行黑盒任务闭环。"""
        resolved = self._resolve_task(task)
        owns_status = resolved.status is TaskStatus.PENDING
        if resolved.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise TaskError(f"黑盒任务状态不允许执行：{resolved.status.value}")
        if owns_status:
            resolved = self._lifecycle.start_task(resolved)

        await self.events.task_start(resolved.task_id, resolved.goal, resolved.start_url or "")

        planner, evaluator = self.llm_boundary.resolve(resolved)
        task_input = self._to_task_input(resolved)

        # ── 关联：创建 BlackboxRun ──
        blackbox_run_id = ""
        correlation_run_id = ""
        if self._create_blackbox_run_fn is not None:
            blackbox_run_id = self._create_blackbox_run_fn(resolved)
        if blackbox_run_id and self._create_correlation_run_fn is not None:
            cr_data = self._create_correlation_run_fn(blackbox_run_id, resolved)
            if cr_data is not None:
                correlation_run_id = cr_data.get("correlation_run_id", "")

        loop = BlackboxExecutionLoop(
            lifecycle=self._lifecycle,
            reader=self._reader,
            action_executor=self.action_executor,
            finalizer=self.finalizer,
            evidence=self.evidence,
            events=self.events,
            recovery_policy=self.recovery_policy,
            max_plan_steps=self.max_plan_steps,
            blackbox_run_id=blackbox_run_id,
        )

        with bind_context(task_id=resolved.task_id):
            try:
                async with self.browser_session_factory(resolved) as session:
                    # ── 设置 origin ──
                    if resolved.start_url:
                        try:
                            origin = extract_origin(resolved.start_url)
                            if origin:
                                session.set_allowed_origins(
                                    [origin],
                                    allow_http_to_https_upgrade=True,
                                )
                        except Exception:
                            pass

                    # ── 启动 writer ──
                    if blackbox_run_id and self._persist_request_batch is not None:
                        _bbid = blackbox_run_id
                        _tid = resolved.task_id
                        session.start_request_writer(
                            lambda batch, bbid=_bbid, tid=_tid: self._persist_requests(
                                batch, bbid, tid
                            )
                        )

                    # ── 设置步骤钩子 ──
                    if blackbox_run_id:

                        async def _on_step_started(
                            task_id: str,
                            step_exec_id: str,
                            attempt: int,
                        ) -> None:
                            session.begin_step(step_exec_id, attempt)

                        async def _on_step_finished(
                            task_id: str,
                            step_exec_id: str,
                            attempt: int,
                        ) -> None:
                            session.end_step(step_exec_id)

                        loop._on_step_started = _on_step_started
                        loop._on_step_finished = _on_step_finished

                    # ── 执行 ──
                    result_status = BlackboxRunStatus.FAILED
                    try:
                        resolved = await loop.run(
                            resolved, task_input, planner, evaluator, session, owns_status
                        )
                        result_status = BlackboxRunStatus.SUCCESS

                    except asyncio.CancelledError:
                        result_status = BlackboxRunStatus.CANCELLED
                        raise

                    except Exception:
                        result_status = BlackboxRunStatus.FAILED
                        raise

                    finally:
                        # ── 完整收尾（shield 防止取消中断）──
                        if blackbox_run_id:
                            try:
                                await asyncio.shield(session.finish_request_capture())
                            except Exception:
                                logger.warning("finish_request_capture 失败", exc_info=True)

                        # ── 持久化采集质量 ──
                        if blackbox_run_id and self._finalize_blackbox_run_fn is not None:
                            try:
                                quality = session.get_capture_quality()
                                from argus_py.correlation.models import CaptureQuality

                                cq = CaptureQuality(
                                    blackbox_run_id=blackbox_run_id,
                                    **quality,
                                )
                                self._finalize_blackbox_run_fn(
                                    blackbox_run_id, result_status.value, cq
                                )
                            except Exception:
                                logger.warning("持久化采集质量失败", exc_info=True)

                        # ── 原子推进 + 认领 ──
                        if (
                            correlation_run_id
                            and self._claim_and_execute_correlation_fn is not None
                        ):
                            try:
                                await self._claim_and_execute_correlation_fn(
                                    correlation_run_id,
                                    self._worker_id,
                                )
                            except Exception:
                                logger.warning("关联认领失败", exc_info=True)

            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                logger.exception("黑盒任务异常：%s", resolved.task_id)
                latest = self._reader.get_latest_task(resolved)
                if owns_status and latest.status is TaskStatus.RUNNING:
                    await self.events.fail(resolved.task_id, str(exc))
                    latest = await self.finalizer.generate_report(latest)
                    self._lifecycle.fail_task(latest, str(exc))
                raise
            finally:
                # 关闭本任务期间由 LLMBoundaryFactory 自建的 LLMClient，
                # 释放底层 httpx.AsyncClient 连接池；外部注入的 client 不会被关闭。
                await self.llm_boundary.aclose_owned(resolved.task_id)

        return resolved

    async def _persist_requests(
        self,
        batch: list[_CapturedRequest],
        blackbox_run_id: str,
        task_id: str,
    ) -> None:
        """将由 BrowserSession 捕获的 _CapturedRequest 批量持久化。"""
        if self._persist_request_batch is None:
            return
        # 将 _CapturedRequest 转换为可序列化的 dict
        dicts: list[dict[str, Any]] = []
        for cap in batch:
            dicts.append(
                {
                    "sequence": cap.sequence,
                    "step_execution_id": cap.step_execution_id,
                    "step_attempt": cap.step_attempt,
                    "page_sequence": cap.page_sequence,
                    "method": cap.method,
                    "origin": cap.origin,
                    "normalized_path": cap.normalized_path,
                    "display_path": cap.display_path,
                    "resource_type": cap.resource_type,
                    "request_owner": cap.request_owner,
                    "path_too_long": cap.path_too_long,
                    "response_status": cap.response_status,
                    "response_from_service_worker": cap.response_from_service_worker,
                    "outcome": cap.outcome.value
                    if hasattr(cap.outcome, "value")
                    else str(cap.outcome),
                    "failure_code": cap.failure_code,
                    "endpoint_match_eligibility": (
                        cap.endpoint_match_eligibility.value
                        if hasattr(cap.endpoint_match_eligibility, "value")
                        else str(cap.endpoint_match_eligibility)
                    ),
                    "started_at": cap.started_at,
                    "finished_at": cap.finished_at,
                    "blackbox_run_id": blackbox_run_id,
                    "task_id": task_id,
                }
            )
        await self._persist_request_batch(dicts)

    def _resolve_task(self, task: Task | BlackboxTaskInput) -> Task:
        """统一任务输入。"""
        if isinstance(task, Task):
            return task
        parameters: dict[str, str | dict[str, str]] = {}
        if task.prompt_extensions:
            parameters["prompt_extensions"] = dict(task.prompt_extensions)
        return self._lifecycle.create_task(
            goal=task.goal,
            start_url=task.start_url,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
            parameters=parameters or None,
        )

    def _to_task_input(self, task: Task) -> BlackboxTaskInput:
        """从任务实体构造黑盒输入。"""
        if not task.start_url:
            raise TaskError("黑盒任务缺少起始 URL。")
        return BlackboxTaskInput(
            goal=task.goal,
            start_url=task.start_url,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            capture_screenshots=task.capture_screenshots,
        )

    def _default_browser_session(self, task: Task) -> BrowserSession:
        """创建默认浏览器会话（复用进程级共享 Playwright 客户端）。"""
        from argus_py.browser.singleton import shared_client

        screenshot_dir: Path = SCREENSHOTS_DIR / task.task_id
        return BrowserSession(
            client=shared_client(),
            screenshot_dir=screenshot_dir,
            stop_browser=False,
        )
