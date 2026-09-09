"""回归批次终态推进与汇总（可维护性 M3）。

sync：由 TaskLifecycleService 终态回调在任务落盘线程内调用。
由 ``RegressionService`` 经 Mixin 组合；公开方法名与行为不变。
内部实现模块——请勿单独实例化。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Callable

from argus_py.core.enums import TaskType
from argus_py.observability.aspect import log_operation
from argus_py.regression._common import _TASK_TO_ITEM_STATUS
from argus_py.regression.diff import (
    MAX_DIFF_ENTRIES_PER_CATEGORY,
    DiffResult,
    GateDecision,
    compute_diff,
    evaluate_gate,
)
from argus_py.regression.enums import RegressionItemStatus, RegressionRunStatus
from argus_py.regression.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintedFinding,
    compute_fingerprint,
)
from argus_py.regression.models import RegressionRun, RegressionRunItem

if TYPE_CHECKING:
    from argus_py.task.storage import TaskSQLiteStorage

logger = logging.getLogger(__name__)


class RunFinalizationMixin:
    """handle_task_terminal / finalize / summary 构建。

    仅组合进 ``RegressionService``；依赖面见 ``_deps.RegressionServiceDeps``。
    """

    # 本 Mixin 实际使用的注入依赖
    _storage: TaskSQLiteStorage
    _publish: Callable[[str, str, dict[str, Any]], None]

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
        decision: GateDecision,
        current_total: int,
        baseline_total: int,
    ) -> dict[str, Any]:
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
