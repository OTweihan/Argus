"""相对基线的差异计算与固定质量门禁判定（纯函数，无 IO）。

差异口径（回归闭环计划 §3.3）：
- 仅比较**同一用例**（case_id 匹配）在当前批次与基线批次中的发现项；
- 以稳定指纹为集合元素，输出新增（added）/持续（persistent）/已解决
  （resolved）三组；
- 门禁固定规则：
  1. 任一批次项子任务 failed/timeout/cancelled ⇒ 批次失败；
  2. 相对基线新增 high/critical 问题 ⇒ 批次失败；
  3. 新增低/中问题、持续与已解决问题只写入差异报告，不阻断。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from argus_py.core.enums import FindingSeverity
from argus_py.regression.enums import (
    RegressionDiffCategory,
    RegressionGateResult,
    RegressionItemStatus,
)
from argus_py.regression.fingerprint import FingerprintedFinding

# 单类别差异明细上限：防止异常任务（如数百 findings）把 summary_json 撑爆。
MAX_DIFF_ENTRIES_PER_CATEGORY = 500

BLOCKING_SEVERITIES: frozenset[str] = frozenset(
    {FindingSeverity.HIGH.value, FindingSeverity.CRITICAL.value}
)
BLOCKING_ITEM_STATUSES: frozenset[RegressionItemStatus] = frozenset(
    {
        RegressionItemStatus.FAILED,
        RegressionItemStatus.TIMEOUT,
        RegressionItemStatus.CANCELLED,
    }
)


@dataclass(frozen=True)
class DiffEntry:
    """单条差异记录。"""

    category: RegressionDiffCategory
    fingerprint: str
    title: str
    severity: str
    finding_type: str
    location: str | None = None
    case_id: str | None = None
    current_task_id: str | None = None
    baseline_task_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "fingerprint": self.fingerprint,
            "title": self.title,
            "severity": self.severity,
            "findingType": self.finding_type,
            "location": self.location,
            "caseId": self.case_id,
            "currentTaskId": self.current_task_id,
            "baselineTaskId": self.baseline_task_id,
        }


@dataclass
class DiffResult:
    """一次批次级差异计算结果。"""

    added: list[DiffEntry] = field(default_factory=list)
    persistent: list[DiffEntry] = field(default_factory=list)
    resolved: list[DiffEntry] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class GateDecision:
    """门禁判定结论。"""

    result: RegressionGateResult
    blocking_reasons: list[str] = field(default_factory=list)


def compute_case_diff(
    baseline_findings: list[FingerprintedFinding],
    current_findings: list[FingerprintedFinding],
) -> tuple[list[DiffEntry], list[DiffEntry], list[DiffEntry]]:
    """计算单个用例的差异三元组（added / persistent / resolved）。

    输入为该 case_id 在基线批次与当前批次中对应子任务的发现项；同指纹
    视为同一问题。展示字段优先取当前批次的记录（resolved 取基线记录）。
    """
    baseline_by_fp = {f.fingerprint: f for f in baseline_findings}
    current_by_fp = {f.fingerprint: f for f in current_findings}

    added: list[DiffEntry] = []
    persistent: list[DiffEntry] = []
    resolved: list[DiffEntry] = []

    for fp, cur in current_by_fp.items():
        entry = DiffEntry(
            category=RegressionDiffCategory.ADDED,
            fingerprint=fp,
            title=cur.title,
            severity=cur.severity,
            finding_type=cur.finding_type,
            location=cur.location,
            case_id=cur.case_id,
            current_task_id=cur.task_id,
        )
        base = baseline_by_fp.get(fp)
        if base is None:
            added.append(entry)
        else:
            persistent.append(
                DiffEntry(
                    category=RegressionDiffCategory.PERSISTENT,
                    fingerprint=fp,
                    title=cur.title,
                    severity=cur.severity,
                    finding_type=cur.finding_type,
                    location=cur.location,
                    case_id=cur.case_id,
                    current_task_id=cur.task_id,
                    baseline_task_id=base.task_id,
                )
            )

    for fp, base in baseline_by_fp.items():
        if fp in current_by_fp:
            continue
        resolved.append(
            DiffEntry(
                category=RegressionDiffCategory.RESOLVED,
                fingerprint=fp,
                title=base.title,
                severity=base.severity,
                finding_type=base.finding_type,
                location=base.location,
                case_id=base.case_id,
                baseline_task_id=base.task_id,
            )
        )

    return added, persistent, resolved


def compute_diff(
    baseline_by_case: Mapping[str, list[FingerprintedFinding]],
    current_by_case: Mapping[str, list[FingerprintedFinding]],
) -> DiffResult:
    """按用例聚合的批次级差异计算。

    只比较两侧都存在的 case_id（基线或当前缺少的用例不参与对比——例如
    基线之后新增的用例首跑无对比意义）。
    """
    result = DiffResult()
    shared_cases = sorted(set(baseline_by_case) & set(current_by_case))
    for case_id in shared_cases:
        added, persistent, resolved = compute_case_diff(
            baseline_by_case[case_id], current_by_case[case_id]
        )
        result.added.extend(added)
        result.persistent.extend(persistent)
        result.resolved.extend(resolved)

    if any(
        len(group) > MAX_DIFF_ENTRIES_PER_CATEGORY
        for group in (result.added, result.persistent, result.resolved)
    ):
        result.truncated = True
    return result


def evaluate_gate(
    item_statuses: Mapping[str, RegressionItemStatus],
    diff: DiffResult,
) -> GateDecision:
    """固定规则质量门禁判定。

    Args:
        item_statuses: case_id → 批次项终态（skipped 不阻断但计入原因说明外
            的统计；此处只关心阻断状态）。
        diff: 相对基线的差异结果。
    """
    reasons: list[str] = []

    for case_id in sorted(item_statuses):
        status = item_statuses[case_id]
        if status not in BLOCKING_ITEM_STATUSES:
            continue
        reasons.append(f"用例 {case_id} 的子任务未成功：{status.value}")

    blocking_added = [e for e in diff.added if e.severity in BLOCKING_SEVERITIES]
    for entry in sorted(blocking_added, key=lambda e: (e.severity, e.case_id or "")):
        reasons.append(f"用例 {entry.case_id} 新增 {entry.severity} 问题：{entry.title}")

    result = RegressionGateResult.FAILED if reasons else RegressionGateResult.PASSED
    return GateDecision(result=result, blocking_reasons=reasons)
