"""回归批次协调应用服务。

线程/协程约定（重要）：
- **async 方法**（``create_run`` / ``cancel_run``）：需要与进程内 TaskQueue
  交互，必须在事件循环上调用；其中同步 SQLite/lifecycle 操作统一经
  ``run_in_thread`` 执行；
- **sync 方法**（用例 CRUD、``handle_task_terminal``、基线管理、恢复扫描、
  查询）：纯 SQLite 操作；API 路由经 ``run_in_thread`` 调用，
  ``handle_task_terminal`` 由 ``TaskLifecycleService`` 的终态回调在任务落盘
  线程内直接调用；TaskRunner 会等待该 IO 工作完成，不在事件循环执行。

批次状态语义：
- ``completed``：批次执行完毕，是否通过质量门禁见 ``gate_result``；
- ``failed``：批次自身失败（队列满载 fail-fast、创建中断、恢复兜底）；
- ``cancelled``：用户显式取消。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from argus_py.core.constants import utc_now_iso
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import ArgusError
from argus_py.core.ids import generate_id
from argus_py.observability.aspect import log_operation
from argus_py.observability.context import run_in_thread
from argus_py.regression.diff import (
    DiffResult,
    compute_diff,
    evaluate_gate,
)
from argus_py.regression.enums import (
    RegressionItemStatus,
    RegressionRunStatus,
    RegressionTriggerSource,
)
from argus_py.regression.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintedFinding,
    compute_fingerprint,
)
from argus_py.regression.models import (
    CaseSnapshot,
    RegressionCase,
    RegressionRun,
    RegressionRunItem,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from argus_py.infra.queue import TaskQueue
    from argus_py.task.lifecycle import TaskLifecycleService
    from argus_py.task.storage import TaskSQLiteStorage

logger = logging.getLogger(__name__)

# 子任务名称前缀：任务列表中可直接识别回归来源
_REGRESSION_NAME_PREFIX = "[回归] "
# 子任务 parameters 中携带的回归关联标识键
REGRESSION_PARAMS_KEY = "regression"

_TASK_TO_ITEM_STATUS: dict[str, RegressionItemStatus] = {
    TaskStatus.PENDING.value: RegressionItemStatus.PENDING,
    TaskStatus.RUNNING.value: RegressionItemStatus.RUNNING,
    TaskStatus.PAUSED.value: RegressionItemStatus.RUNNING,
    TaskStatus.COMPLETED.value: RegressionItemStatus.COMPLETED,
    TaskStatus.FAILED.value: RegressionItemStatus.FAILED,
    TaskStatus.TIMEOUT.value: RegressionItemStatus.TIMEOUT,
    TaskStatus.CANCELLED.value: RegressionItemStatus.CANCELLED,
}

_ITEM_TERMINAL_STATUSES: frozenset[RegressionItemStatus] = frozenset(
    {
        RegressionItemStatus.COMPLETED,
        RegressionItemStatus.FAILED,
        RegressionItemStatus.TIMEOUT,
        RegressionItemStatus.CANCELLED,
        RegressionItemStatus.SKIPPED,
    }
)


class RegressionError(ArgusError):
    """回归业务错误，携带稳定错误码与 HTTP 语义。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.details = details or {}


class _QueueFullAbort(Exception):
    """提交阶段命中队列容量上限的内部信号。"""


class RegressionService:
    """项目级回归闭环编排：用例 → 批次 → 终态汇总与门禁。"""

    def __init__(
        self,
        *,
        storage: "TaskSQLiteStorage",
        lifecycle: "TaskLifecycleService",
        queue: "TaskQueue",
        resolve_create_params: "Callable[..., dict[str, Any]]",
        event_publisher: "Callable[[str, str, dict[str, Any]], None] | None" = None,
    ) -> None:
        self._storage = storage
        self._lifecycle = lifecycle
        self._queue = queue
        # TaskApplicationService.resolve_create_params：用例保存时做与任务创建
        # 完全一致的校验与默认值合并（CLI 与 API 共用同一应用服务约束）
        self._resolve_create_params = resolve_create_params
        self._publish = event_publisher or (lambda *args, **kwargs: None)

    # ══════════════════════════════════════════════════════════
    # 用例 CRUD（sync）
    # ══════════════════════════════════════════════════════════

    def create_case(self, project_id: str, input: dict[str, Any]) -> RegressionCase:
        """创建回归用例；输入经任务创建同一套校验后存储解析结果。"""
        snapshot = self._validate_case_input(project_id, input)
        now = utc_now_iso()
        case = RegressionCase(
            case_id=generate_id("regcase"),
            project_id=project_id,
            name=snapshot.name,
            task_type=snapshot.task_type,
            goal=snapshot.goal,
            start_url=snapshot.start_url,
            max_steps=snapshot.max_steps,
            timeout_seconds=snapshot.timeout_seconds,
            capture_screenshots=snapshot.capture_screenshots,
            parameters_json=json.dumps(snapshot.parameters, ensure_ascii=False),
            whitebox_config_json=snapshot.whitebox_config_json,
            enabled=bool(input.get("enabled", True)),
            display_order=int(input.get("displayOrder", 0) or 0),
            created_at=now,
            updated_at=now,
        )
        return self._storage.create_regression_case(case)

    def update_case(self, case_id: str, updates: dict[str, Any]) -> RegressionCase:
        """更新用例：合并现有配置后整体重新校验，保证存量始终可执行。"""
        case = self._require_case(case_id)
        merged: dict[str, Any] = {
            "taskType": case.task_type.value,
            "goal": case.goal,
            "startUrl": case.start_url,
            "parameters": case.resolved_parameters(),
            "enabled": case.enabled,
            "displayOrder": case.display_order,
        }
        for key in ("name", "goal", "startUrl", "enabled", "displayOrder"):
            if key in updates:
                merged[key] = updates[key]
        if "maxSteps" in updates:
            merged["maxSteps"] = updates["maxSteps"]
        if "timeoutSeconds" in updates:
            merged["timeoutSeconds"] = updates["timeoutSeconds"]
        if "captureScreenshots" in updates and updates["captureScreenshots"] is not None:
            merged["captureScreenshots"] = updates["captureScreenshots"]
        if "parameters" in updates and updates["parameters"] is not None:
            merged["parameters"] = updates["parameters"]
        # taskType 不允许变更：黑盒/白盒输入结构差异过大，改建新用例
        snapshot = self._validate_case_input(
            case.project_id,
            {**merged, "taskType": case.task_type.value},
            fallback_limits=(case.max_steps, case.timeout_seconds, case.capture_screenshots),
        )
        fields: dict[str, Any] = {
            "name": snapshot.name,
            "goal": snapshot.goal,
            "start_url": snapshot.start_url,
            "max_steps": snapshot.max_steps,
            "timeout_seconds": snapshot.timeout_seconds,
            "capture_screenshots": int(snapshot.capture_screenshots),
            "parameters_json": json.dumps(snapshot.parameters, ensure_ascii=False),
            "whitebox_config_json": snapshot.whitebox_config_json,
            "enabled": int(bool(merged.get("enabled", True))),
            "display_order": int(merged.get("displayOrder", 0) or 0),
            "updated_at": utc_now_iso(),
        }
        self._storage.update_regression_case(case_id, fields)
        updated = self._require_case(case_id)
        return updated

    def delete_case(self, case_id: str) -> None:
        """删除用例。历史批次使用快照，不受影响。"""
        self._require_case(case_id)
        self._storage.delete_regression_case(case_id)

    def get_case(self, case_id: str) -> RegressionCase:
        return self._require_case(case_id)

    def list_cases(self, project_id: str, *, enabled_only: bool = False) -> list[RegressionCase]:
        return self._storage.list_regression_cases(project_id, enabled_only=enabled_only)

    def _require_case(self, case_id: str) -> RegressionCase:
        case = self._storage.get_regression_case(case_id)
        if case is None:
            raise RegressionError(
                "REGRESSION_CASE_NOT_FOUND",
                f"回归用例不存在：{case_id}",
                http_status=404,
                details={"caseId": case_id},
            )
        return case

    def _validate_case_input(
        self,
        project_id: str,
        input: dict[str, Any],
        fallback_limits: tuple[int, int, bool] | None = None,
    ) -> CaseSnapshot:
        """校验用例输入并返回解析后的可执行快照。

        复用 ``resolve_create_params``：URL 校验、项目默认值合并、模型配置
        存在性校验、白盒配置 schema 校验与执行限制推断一次完成。
        """
        task_type_raw = input.get("taskType") or TaskType.BLACKBOX.value
        try:
            task_type = TaskType(task_type_raw)
        except ValueError as exc:
            raise RegressionError(
                "REGRESSION_INVALID_INPUT",
                f"不支持的任务类型：{task_type_raw}",
                details={"field": "taskType"},
            ) from exc

        goal = str(input.get("goal") or "").strip()
        if not goal:
            raise RegressionError(
                "REGRESSION_INVALID_INPUT",
                "回归用例需要测试目标（goal）。",
                details={"field": "goal"},
            )

        fb_max_steps, fb_timeout, fb_capture = fallback_limits or (None, None, None)
        try:
            resolved = self._resolve_create_params(
                goal=goal,
                name=str(input.get("name") or "").strip() or None,
                start_url=input.get("startUrl") or None,
                task_type=task_type,
                project_id=project_id or None,
                max_steps=input.get("maxSteps")
                if input.get("maxSteps") is not None
                else fb_max_steps,
                timeout_seconds=(
                    input.get("timeoutSeconds")
                    if input.get("timeoutSeconds") is not None
                    else fb_timeout
                ),
                capture_screenshots=(
                    input.get("captureScreenshots")
                    if input.get("captureScreenshots") is not None
                    else fb_capture
                ),
                parameters=input.get("parameters") or {},
            )
        except ArgusError:
            raise
        except Exception as exc:
            raise RegressionError(
                "REGRESSION_INVALID_INPUT",
                f"用例配置校验失败：{exc}",
                details={"projectId": project_id},
            ) from exc

        name = str(input.get("name") or "").strip()
        if not name:
            name = goal[:40]
        raw_capture = resolved.get("capture_screenshots")
        return CaseSnapshot(
            case_id="",
            name=name,
            task_type=task_type,
            goal=resolved["goal"],
            start_url=resolved.get("start_url"),
            max_steps=int(resolved["max_steps"]),
            timeout_seconds=int(resolved["timeout_seconds"]),
            capture_screenshots=True if raw_capture is None else bool(raw_capture),
            parameters=dict(resolved.get("parameters") or {}),
            whitebox_config_json=resolved.get("whitebox_config_json"),
        )

    # ══════════════════════════════════════════════════════════
    # 批次创建 / 取消（async —— 需要与 TaskQueue 交互）
    # ══════════════════════════════════════════════════════════

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

        submitted: list[tuple[RegressionRunItem, str]] = []
        try:
            for item in items:
                task = await run_in_thread(self._create_item_task, run, item)
                submitted.append((item, task.task_id))
                result = await self._queue.try_enqueue(task.task_id)
                if result.rejected:
                    raise _QueueFullAbort()
        except _QueueFullAbort:
            await self._abort_on_queue_full(run.run_id, items, submitted)
            raise RegressionError(
                "TASK_QUEUE_FULL",
                "任务队列已满，回归批次已中止；请稍后重试。",
                http_status=503,
                details={"runId": run.run_id, "submitted": len(submitted)},
            )

        await run_in_thread(self._storage.mark_regression_running, run.run_id)
        persisted = await run_in_thread(self._storage.get_regression_run, run.run_id)
        return persisted or run

    def _create_item_task(self, run: RegressionRun, item: RegressionRunItem) -> Any:
        """按批次项快照创建子任务并回填关联。"""
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
        task = self._lifecycle.create_task(
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
        self._storage.attach_regression_task(item.item_id, task.task_id)
        return task

    async def _abort_on_queue_full(
        self,
        run_id: str,
        items: list[RegressionRunItem],
        submitted: list[tuple[RegressionRunItem, str]],
    ) -> None:
        """队列满载 fail-fast：批次先落 FAILED（阻断终态回调路径），再回收子任务。

        顺序很关键：若先取消子任务，其终态回调会在批次仍为 pending 时触发
        正常 finalize（COMPLETED），与失败语义竞态。先 CAS 占住终态后，回调
        自动忽略；批次项状态在此显式镜像。
        """
        submitted_ids = {task_id for _, task_id in submitted}
        submitted_items = {item.item_id for item, _ in submitted}
        await run_in_thread(
            self._storage.finalize_regression_run,
            run_id=run_id,
            status=RegressionRunStatus.FAILED,
            gate_result=None,
            summary_json=json.dumps({"fingerprintVersion": FINGERPRINT_VERSION}),
            error_code="REGRESSION_QUEUE_FULL",
            error_message=f"任务队列满载，仅 {len(submitted_ids)} 个子任务进入执行。",
        )
        self._publish(
            "regression.batch.finalized",
            run_id,
            {"runId": run_id, "status": RegressionRunStatus.FAILED.value},
        )

        # 已入队未执行的子任务移出队列并取消；已在执行的保留跑完（结果仍在
        # 任务列表可见）。批次项状态同步镜像为终态。
        terminal_statuses = (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        )
        for item in items:
            if item.item_id not in submitted_items:
                await run_in_thread(
                    self._storage.update_regression_item_status,
                    item.item_id,
                    RegressionItemStatus.SKIPPED,
                    error_code="BATCH_ABORTED_QUEUE_FULL",
                )
        for item, task_id in submitted:
            mirrored = False
            try:
                sched = await self._queue.scheduler_status(task_id)
                if sched == "running":
                    # 已在执行的子任务保留跑完；批次项保持 running，由其终态
                    # 回调……不会更新（批次已终态）。这里显式镜像为 cancelled
                    # 并注明任务仍在执行，结果可在任务列表查看。
                    await run_in_thread(
                        self._storage.update_regression_item_status,
                        item.item_id,
                        RegressionItemStatus.CANCELLED,
                        error_code="BATCH_ABORTED_TASK_RUNNING",
                        error_message="批次已中止，该子任务继续执行至结束（结果不计入本批次）。",
                    )
                    mirrored = True
                    continue
                if sched == "queued":
                    await self._queue.cancel(task_id)
                task = await run_in_thread(self._lifecycle.storage.load, task_id)
                if task.status not in terminal_statuses:
                    await run_in_thread(self._lifecycle.cancel_task, task)
            except Exception:
                logger.debug("回归批次中止回收子任务失败: %s", task_id, exc_info=True)
            finally:
                if not mirrored:
                    # 已取消/未开始的子任务：批次项显式收口为 cancelled
                    await run_in_thread(
                        self._storage.update_regression_item_status,
                        item.item_id,
                        RegressionItemStatus.CANCELLED,
                        error_code="BATCH_ABORTED_QUEUE_FULL",
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
        for item in items:
            if item.status in _ITEM_TERMINAL_STATUSES:
                continue
            if item.task_id is None:
                await run_in_thread(
                    self._storage.update_regression_item_status,
                    item.item_id,
                    RegressionItemStatus.SKIPPED,
                    error_code="BATCH_CANCELLED",
                )
                continue
            try:
                sched = await self._queue.scheduler_status(item.task_id)
                if sched == "queued":
                    await self._queue.cancel(item.task_id)
                self._lifecycle.get_cancellation_token(item.task_id).cancel()
                task = await run_in_thread(self._lifecycle.storage.load, item.task_id)
                if task.status not in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.TIMEOUT,
                    TaskStatus.CANCELLED,
                ):
                    await run_in_thread(self._lifecycle.cancel_task, task)
            except Exception:
                logger.debug(
                    "取消批次子任务失败: run=%s task=%s", run_id, item.task_id, exc_info=True
                )
            finally:
                # 批次已终态、终态回调被阻断：批次项状态在此显式收口
                await run_in_thread(
                    self._storage.update_regression_item_status,
                    item.item_id,
                    RegressionItemStatus.CANCELLED,
                    error_code="BATCH_CANCELLED",
                )
        self._publish(
            "regression.batch.finalized",
            run_id,
            {"runId": run_id, "status": RegressionRunStatus.CANCELLED.value},
        )
        return await run_in_thread(self._require_run, run_id)

    # ══════════════════════════════════════════════════════════
    # 终态推进（sync —— 由 TaskLifecycleService 终态回调驱动）
    # ══════════════════════════════════════════════════════════

    def handle_task_terminal(self, task_id: str, status_value: str) -> None:
        """任务终态回调：镜像批次项状态，全部终态时收尾批次。

        任何异常都不得向调用方传播（任务主流程优先）；失败场景由启动恢复
        兜底。
        """
        try:
            self._handle_task_terminal(task_id, status_value)
        except Exception:
            logger.exception("回归批次终态推进失败: task=%s status=%s", task_id, status_value)

    @log_operation("regression.task_terminal", task_arg="task_id")
    def _handle_task_terminal(self, task_id: str, status_value: str) -> None:
        item = self._storage.get_regression_item_by_task_id(task_id)
        if item is None:
            return
        run = self._storage.get_regression_run(item.run_id)
        if run is None or run.status not in (
            RegressionRunStatus.PENDING,
            RegressionRunStatus.RUNNING,
        ):
            return
        mapped = _TASK_TO_ITEM_STATUS.get(status_value)
        if mapped is None or mapped in (RegressionItemStatus.PENDING, RegressionItemStatus.RUNNING):
            return

        finding_counts = self._storage.count_findings_by_task_ids([task_id])
        self._storage.update_regression_item_status(
            item.item_id,
            mapped,
            finding_count=finding_counts.get(task_id, 0),
            error_code=(
                None if mapped is RegressionItemStatus.COMPLETED else f"TASK_{status_value.upper()}"
            ),
            error_message=None,
        )
        self._publish(
            "regression.batch.item_finished",
            run.run_id,
            {
                "runId": run.run_id,
                "itemId": item.item_id,
                "taskId": task_id,
                "status": mapped.value,
            },
        )
        self._maybe_finalize(run.run_id)

    def _maybe_finalize(self, run_id: str) -> None:
        counts = self._storage.count_regression_item_statuses(run_id)
        active = counts.get(RegressionItemStatus.PENDING.value, 0) + counts.get(
            RegressionItemStatus.RUNNING.value, 0
        )
        if active:
            return
        run = self._storage.get_regression_run(run_id)
        if run is None or run.status not in (
            RegressionRunStatus.PENDING,
            RegressionRunStatus.RUNNING,
        ):
            return
        self._finalize(run)

    def _finalize(self, run: RegressionRun) -> None:
        """计算相对基线的差异与固定门禁，CAS 收尾批次。"""
        items = self._storage.get_regression_items(run.run_id)
        counts = self._storage.count_regression_item_statuses(run.run_id)

        current_task_ids = [i.task_id for i in items if i.task_id]
        current_findings = self._storage.list_findings_by_task_ids(current_task_ids)
        current_by_case: dict[str, list[FingerprintedFinding]] = {}
        current_total = 0
        for item in items:
            findings = current_findings.get(item.task_id, []) if item.task_id else []
            current_total += len(findings)
            task_type = self._snapshot_task_type(item)
            current_by_case[item.case_id] = [
                self._to_fingerprinted(task_type, item, finding, task_id=item.task_id)
                for finding in findings
            ]

        baseline_total = 0
        baseline_by_case: dict[str, list[FingerprintedFinding]] = {}
        if run.baseline_run_id:
            baseline_items = self._storage.get_regression_items(run.baseline_run_id)
            baseline_task_ids = [i.task_id for i in baseline_items if i.task_id]
            baseline_findings = self._storage.list_findings_by_task_ids(baseline_task_ids)
            for item in baseline_items:
                findings = baseline_findings.get(item.task_id, []) if item.task_id else []
                baseline_total += len(findings)
                task_type = self._snapshot_task_type(item)
                baseline_by_case[item.case_id] = [
                    self._to_fingerprinted(task_type, item, finding, task_id=item.task_id)
                    for finding in findings
                ]

        diff = compute_diff(baseline_by_case, current_by_case)
        statuses = {item.case_id: item.status for item in items}
        decision = evaluate_gate(statuses, diff)

        summary = self._build_summary(
            run=run,
            counts=counts,
            diff=diff,
            decision=decision,
            current_total=current_total,
            baseline_total=baseline_total,
        )
        finalized = self._storage.finalize_regression_run(
            run_id=run.run_id,
            status=RegressionRunStatus.COMPLETED,
            gate_result=decision.result,
            summary_json=json.dumps(summary, ensure_ascii=False),
        )
        if finalized:
            logger.info(
                "回归批次完成: run=%s gate=%s added=%d persistent=%d resolved=%d",
                run.run_id,
                decision.result.value,
                len(diff.added),
                len(diff.persistent),
                len(diff.resolved),
            )
            self._publish(
                "regression.batch.finalized",
                run.run_id,
                {
                    "runId": run.run_id,
                    "status": RegressionRunStatus.COMPLETED.value,
                    "gateResult": decision.result.value,
                },
            )

    @staticmethod
    def _snapshot_task_type(item: RegressionRunItem) -> TaskType:
        """解析批次项快照中的任务类型（每个批次项只解析一次）。"""
        try:
            raw = json.loads(item.case_snapshot_json) if item.case_snapshot_json else {}
        except (TypeError, ValueError):
            raw = {}
        return TaskType(raw.get("task_type", TaskType.BLACKBOX.value))

    @staticmethod
    def _to_fingerprinted(
        task_type: TaskType,
        item: RegressionRunItem,
        finding: Any,
        *,
        task_id: str | None,
    ) -> FingerprintedFinding:
        severity = getattr(finding.severity, "value", finding.severity)
        finding_type = getattr(finding.finding_type, "value", finding.finding_type)
        location = finding.location or finding.url
        return FingerprintedFinding(
            fingerprint=compute_fingerprint(
                task_type, finding_type, severity, finding.title, location
            ),
            title=finding.title,
            severity=str(severity),
            finding_type=str(finding_type),
            location=location,
            task_id=task_id,
            case_id=item.case_id,
        )

    @staticmethod
    def _build_summary(
        *,
        run: RegressionRun,
        counts: dict[str, int],
        diff: DiffResult,
        decision: Any,
        current_total: int,
        baseline_total: int,
    ) -> dict[str, Any]:
        from argus_py.regression.diff import MAX_DIFF_ENTRIES_PER_CATEGORY

        def cap(entries: list[Any]) -> list[dict[str, object]]:
            return [e.to_dict() for e in entries[:MAX_DIFF_ENTRIES_PER_CATEGORY]]

        return {
            "fingerprintVersion": FINGERPRINT_VERSION,
            "baselineRunId": run.baseline_run_id,
            "gateResult": decision.result.value,
            "blockingReasons": list(decision.blocking_reasons),
            "itemCounts": {
                "total": sum(counts.values()),
                **counts,
            },
            "findingTotals": {"current": current_total, "baseline": baseline_total},
            "diff": {
                "addedCount": len(diff.added),
                "persistentCount": len(diff.persistent),
                "resolvedCount": len(diff.resolved),
                "added": cap(diff.added),
                "persistent": cap(diff.persistent),
                "resolved": cap(diff.resolved),
                "truncated": diff.truncated,
            },
        }

    # ══════════════════════════════════════════════════════════
    # 基线（sync）
    # ══════════════════════════════════════════════════════════

    def set_baseline(self, run_id: str) -> RegressionRun:
        """将成功批次设为其项目的基线（仅 completed 批次）。"""
        from argus_py.task.repositories.regression_repo import BaselineConflictError

        run = self._require_run(run_id)
        if run.status is not RegressionRunStatus.COMPLETED:
            raise RegressionError(
                "BASELINE_ONLY_COMPLETED_BATCH",
                f"只有执行完毕的批次可以设为基线，当前状态：{run.status.value}。",
                http_status=409,
                details={"runId": run_id, "status": run.status.value},
            )
        try:
            ok = self._storage.set_regression_baseline(run.project_id, run_id)
        except BaselineConflictError as exc:
            raise RegressionError(
                "BASELINE_CONFLICT",
                str(exc),
                http_status=409,
                details={"runId": run_id},
            ) from exc
        if not ok:
            raise RegressionError(
                "BASELINE_SET_FAILED",
                f"设置基线失败：批次 {run_id} 不可用或不属于该项目。",
                http_status=409,
                details={"runId": run_id},
            )
        return self._require_run(run_id)

    def get_baseline(self, project_id: str) -> RegressionRun | None:
        return self._storage.get_regression_baseline(project_id)

    # ══════════════════════════════════════════════════════════
    # 查询（sync）
    # ══════════════════════════════════════════════════════════

    def get_run(self, run_id: str) -> RegressionRun:
        return self._require_run(run_id)

    def list_runs(
        self,
        project_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        status: RegressionRunStatus | None = None,
    ) -> tuple[list[RegressionRun], int]:
        return self._storage.list_regression_runs(
            project_id, offset=offset, limit=limit, status=status
        )

    def get_run_items(self, run_id: str) -> list[dict[str, Any]]:
        """批次项列表，附实时任务状态（tasks 表为权威）。"""
        items = self._storage.get_regression_items(run_id)
        result: list[dict[str, Any]] = []
        for item in items:
            data: dict[str, Any] = {
                "itemId": item.item_id,
                "runId": item.run_id,
                "caseId": item.case_id,
                "caseName": item.case_name,
                "displayOrder": item.display_order,
                "taskId": item.task_id,
                "status": item.status.value,
                "findingCount": item.finding_count,
                "errorCode": item.error_code,
                "errorMessage": item.error_message,
                "createdAt": item.created_at,
                "taskStatus": None,
            }
            if item.task_id:
                header = self._storage.load_task_header(item.task_id)
                if header is not None:
                    data["taskStatus"] = header.get("status")
            result.append(data)
        return result

    def get_run_summary(self, run_id: str) -> dict[str, Any]:
        """返回批次持久化汇总（含差异明细与门禁原因）。"""
        run = self._require_run(run_id)
        try:
            parsed = json.loads(run.summary_json)
        except (TypeError, ValueError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _require_run(self, run_id: str) -> RegressionRun:
        run = self._storage.get_regression_run(run_id)
        if run is None:
            raise RegressionError(
                "REGRESSION_RUN_NOT_FOUND",
                f"回归批次不存在：{run_id}",
                http_status=404,
                details={"runId": run_id},
            )
        return run

    # ══════════════════════════════════════════════════════════
    # 崩溃恢复（sync —— Worker 启动 reconciliation 调用）
    # ══════════════════════════════════════════════════════════

    def recover_stale_runs(self) -> int:
        """启动恢复：对账非终态批次的批次项并尽量收尾。

        - 批次项无 task_id / 任务行丢失 → cancelled（本应执行而未执行，
          必须让门禁显式失败；skipped 是非阻断状态，会误放行全中断批次）；
        - 子任务仍为非终态（进程重启后内存队列已丢，永远无人执行）→ 取消
          子任务并将批次项置 cancelled；
        - 全部批次项终态后走正常 finalize（差异 + 门禁 + CAS 幂等）。
        返回收尾的批次数。失败不抛出——由调用方记录日志。
        """
        recovered = 0
        try:
            runs = self._storage.list_unfinished_regression_runs()
        except Exception:
            logger.exception("回归批次恢复扫描失败")
            return 0
        for run in runs:
            try:
                if self._recover_one(run):
                    recovered += 1
            except Exception:
                logger.exception("回归批次恢复失败: run=%s", run.run_id)
        return recovered

    def _recover_one(self, run: RegressionRun) -> bool:
        items = self._storage.get_regression_items(run.run_id)
        if not items:
            # 防御：正常路径不可能出现空批次
            self._storage.finalize_regression_run(
                run_id=run.run_id,
                status=RegressionRunStatus.FAILED,
                gate_result=None,
                summary_json=json.dumps({"fingerprintVersion": FINGERPRINT_VERSION}),
                error_code="REGRESSION_RUN_EMPTY",
                error_message="批次没有任何批次项。",
            )
            return True

        for item in items:
            if item.status in _ITEM_TERMINAL_STATUSES:
                continue
            if item.task_id is None:
                self._storage.update_regression_item_status(
                    item.item_id,
                    RegressionItemStatus.CANCELLED,
                    error_code="TASK_MISSING",
                    error_message="进程重启导致批次创建中断，该用例未提交执行。",
                )
                continue
            header = self._storage.load_task_header(item.task_id)
            if header is None:
                self._storage.update_regression_item_status(
                    item.item_id,
                    RegressionItemStatus.CANCELLED,
                    error_code="TASK_DELETED",
                    error_message="子任务已被删除，该用例未产生结果。",
                )
                continue
            task_status = header.get("status")
            mapped = _TASK_TO_ITEM_STATUS.get(str(task_status))
            if mapped in _ITEM_TERMINAL_STATUSES:
                finding_counts = self._storage.count_findings_by_task_ids([item.task_id])
                self._storage.update_regression_item_status(
                    item.item_id,
                    mapped or RegressionItemStatus.SKIPPED,
                    finding_count=finding_counts.get(item.task_id, 0),
                )
                continue
            # 非终态任务在重启后永远不会被执行（队列在内存中）——取消并计为
            # 批次项 cancelled，使门禁显式失败而非静默悬挂。
            try:
                task = self._lifecycle.storage.load(item.task_id)
                self._lifecycle.cancel_task(task)
            except Exception:
                logger.warning(
                    "恢复批次时取消孤儿子任务失败: run=%s task=%s",
                    run.run_id,
                    item.task_id,
                    exc_info=True,
                )
                continue
            self._storage.update_regression_item_status(
                item.item_id,
                RegressionItemStatus.CANCELLED,
                error_code="INTERRUPTED_BY_RESTART",
                error_message="进程重启导致子任务未执行。",
            )

        before = run.status
        self._maybe_finalize(run.run_id)
        after = self._storage.get_regression_run(run.run_id)
        finalized = after is not None and after.status in (
            RegressionRunStatus.COMPLETED,
            RegressionRunStatus.FAILED,
            RegressionRunStatus.CANCELLED,
        )
        logger.info("回归批次恢复: run=%s before=%s finalized=%s", run.run_id, before, finalized)
        return finalized
