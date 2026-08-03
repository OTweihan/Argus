"""阶段三：匹配器执行辅助 — 采集质量评估与完整性决策。

供 container.py（异步路径）和 application.py（同步路径）共用，
避免 ~80 行重复的采集质量检查与 reason/diagnostic 构造逻辑。
"""

from __future__ import annotations

from typing import Any

from argus_py.correlation.enums import (
    EvidenceCompleteness,
    PartialReasonCode,
)
from argus_py.correlation.models import (
    CorrelationAttemptDiagnostic,
    CorrelationAttemptReason,
)


def assess_capture_quality(cq: dict[str, Any] | None) -> tuple[bool, bool]:
    """从 CaptureQuality dict 提取截断和持久化失败标志。

    Returns:
        (capture_truncated, has_persistence_failure)
    """
    if cq is None:
        return False, False
    truncated = bool(cq.get("truncated", 0))
    failed = bool(cq.get("persistence_failed", 0))
    writer_failed = bool(cq.get("writer_failed_batch_count", 0))
    return truncated, failed or writer_failed


def build_quality_reasons(
    attempt_id: str,
    cq: dict[str, Any] | None,
    capture_truncated: bool,
    has_persistence_failure: bool,
) -> tuple[list[CorrelationAttemptReason], list[CorrelationAttemptDiagnostic]]:
    """根据采集质量构造 reasons 和 diagnostics 列表。

    调用方负责在无 eligible_requests 时追加 NO_ELIGIBLE_REQUESTS diagnostic。
    """
    reasons: list[CorrelationAttemptReason] = []
    diagnostics: list[CorrelationAttemptDiagnostic] = []

    if capture_truncated:
        reasons.append(
            CorrelationAttemptReason(
                correlation_attempt_id=attempt_id,
                reason_code=PartialReasonCode.CAPTURE_TRUNCATED,
                detail=cq.get("truncation_reason") if cq else "采集被截断",
            )
        )
    if has_persistence_failure:
        reasons.append(
            CorrelationAttemptReason(
                correlation_attempt_id=attempt_id,
                reason_code=PartialReasonCode.REQUEST_PERSISTENCE_FAILED,
                detail=(
                    f"持久化失败: {cq.get('persistence_failed', 0)} 条, "
                    f"writer 批次失败: {cq.get('writer_failed_batch_count', 0)}"
                    if cq
                    else "持久化失败"
                ),
            )
        )

    return reasons, diagnostics


def resolve_completeness(
    has_reasons: bool,
    capture_truncated: bool,
    has_persistence_failure: bool,
) -> EvidenceCompleteness:
    """根据质量标志确定 attempt 完整性结论。

    - 有截断或持久化失败 → PARTIAL
    - 否则 → COMPLETE
    """
    if has_reasons or capture_truncated or has_persistence_failure:
        return EvidenceCompleteness.PARTIAL
    return EvidenceCompleteness.COMPLETE
