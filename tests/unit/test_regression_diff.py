"""差异计算与固定质量门禁单元测试。"""

from __future__ import annotations

from argus_py.regression.diff import (
    MAX_DIFF_ENTRIES_PER_CATEGORY,
    DiffEntry,
    RegressionDiffCategory,
    compute_case_diff,
    compute_diff,
    evaluate_gate,
)
from argus_py.regression.enums import RegressionGateResult, RegressionItemStatus
from argus_py.regression.fingerprint import FingerprintedFinding, compute_fingerprint


def _fp_finding(
    title: str,
    *,
    severity: str = "high",
    case_id: str = "case-1",
    task_id: str | None = "t1",
) -> FingerprintedFinding:
    return FingerprintedFinding(
        fingerprint=compute_fingerprint("blackbox", "functional", severity, title, None),
        title=title,
        severity=severity,
        finding_type="functional",
        location=None,
        task_id=task_id,
        case_id=case_id,
    )


class TestCaseDiff:
    def test_added_persistent_resolved(self) -> None:
        baseline = [_fp_finding("问题A"), _fp_finding("问题B", severity="low")]
        current = [
            _fp_finding("问题A"),
            _fp_finding("问题C", severity="critical"),
        ]
        added, persistent, resolved = compute_case_diff(baseline, current)
        assert [e.title for e in added] == ["问题C"]
        assert [e.title for e in persistent] == ["问题A"]
        assert [e.title for e in resolved] == ["问题B"]

    def test_entry_carries_task_and_case_ids(self) -> None:
        baseline = [_fp_finding("旧问题", task_id="base-t")]
        current = [_fp_finding("旧问题", task_id="cur-t")]
        _, persistent, _ = compute_case_diff(baseline, current)
        assert len(persistent) == 1
        assert persistent[0].current_task_id == "cur-t"
        assert persistent[0].baseline_task_id == "base-t"
        assert persistent[0].case_id == "case-1"


class TestComputeDiff:
    def test_only_shared_cases_compared(self) -> None:
        baseline = {"case-a": [_fp_finding("A1")], "case-b": [_fp_finding("B1")]}
        current = {
            "case-a": [_fp_finding("A1"), _fp_finding("A2")],
            "case-new": [_fp_finding("N1")],
        }
        result = compute_diff(baseline, current)
        # case-new 无基线对照 → 不产生差异；case-b 已从用例集移除 → 不算已解决
        assert [e.title for e in result.added] == ["A2"]
        assert result.resolved == []

    def test_truncation_flag(self) -> None:
        baseline = {"c": [_fp_finding("基线问题", severity="low")]}
        many_current = {
            "c": [
                _fp_finding(f"问题{i:04d}", severity="medium", task_id=f"t{i}")
                for i in range(MAX_DIFF_ENTRIES_PER_CATEGORY + 1)
            ],
        }
        result = compute_diff(baseline, many_current)
        assert result.truncated is True


class TestEvaluateGate:
    def test_all_completed_no_findings_passes(self) -> None:
        decision = evaluate_gate({"c": RegressionItemStatus.COMPLETED}, compute_diff({}, {}))
        assert decision.result is RegressionGateResult.PASSED
        assert decision.blocking_reasons == []

    def test_failed_item_blocks(self) -> None:
        diff = compute_diff({}, {})
        for status in (
            RegressionItemStatus.FAILED,
            RegressionItemStatus.TIMEOUT,
            RegressionItemStatus.CANCELLED,
        ):
            decision = evaluate_gate({"c": status}, diff)
            assert decision.result is RegressionGateResult.FAILED
            assert any("c" in r for r in decision.blocking_reasons)

    def test_new_high_or_critical_blocks_low_medium_does_not(self) -> None:
        low_base = _fp_finding("基线低危", severity="low")
        high_added = DiffEntry(
            category=RegressionDiffCategory.ADDED,
            fingerprint="f1",
            title="高危新问题",
            severity="high",
            finding_type="functional",
        )
        medium_added = DiffEntry(
            category=RegressionDiffCategory.ADDED,
            fingerprint="f2",
            title="中危新问题",
            severity="medium",
            finding_type="functional",
        )
        from argus_py.regression.diff import DiffResult

        passed = evaluate_gate(
            {"c": RegressionItemStatus.COMPLETED},
            compute_diff({"c": [low_base]}, {"c": [low_base]}),
        )
        blocked = evaluate_gate(
            {"c": RegressionItemStatus.COMPLETED},
            compute_diff({"c": [low_base]}, {"c": [low_base, _fp_finding("新高危")]}),
        )
        # 直接构造：medium 新增不阻断
        medium_only = DiffResult(added=[medium_added])
        high_only = DiffResult(added=[high_added])
        assert passed.result is RegressionGateResult.PASSED
        assert blocked.result is RegressionGateResult.FAILED
        assert (
            evaluate_gate({"c": RegressionItemStatus.COMPLETED}, medium_only).result
            is RegressionGateResult.PASSED
        )
        # high 新增阻断且原因含标题
        decision = evaluate_gate({"c": RegressionItemStatus.COMPLETED}, high_only)
        assert decision.result is RegressionGateResult.FAILED
        assert any("高危新问题" in r for r in decision.blocking_reasons)
