"""阶段三：黑白盒关联 — 数据类。"""

from __future__ import annotations

from dataclasses import dataclass, field

from argus_py.correlation.enums import (
    AttemptDiagnosticCode,
    AttemptStatus,
    BlackboxRunStatus,
    CorrelationEligibility,
    CorrelationRunStatus,
    EvidenceCompleteness,
    FindingRelationType,
    MatchConfidence,
    MatchStrategy,
    PartialReasonCode,
    RequestOutcome,
    RequestOwner,
    ResolutionStatus,
    SourceAlignmentStatus,
)

# ── BlackboxRun ──────────────────────────────────────────────


@dataclass
class BlackboxRun:
    """黑盒执行实例。"""

    blackbox_run_id: str  # PK
    task_id: str  # FK → tasks
    attempt: int
    status: BlackboxRunStatus
    started_at: str
    completed_at: str | None = None


# ── CorrelationRun ───────────────────────────────────────────


@dataclass
class CorrelationRun:
    """黑白盒关联运行记录。"""

    correlation_run_id: str
    project_id: str
    blackbox_run_id: str  # FK → blackbox_runs

    # 期望目标（创建时固定）
    desired_source_snapshot_id: str
    desired_analysis_config_digest: str = ""
    required_analyzer_version: str = ""
    allow_partial_analysis: bool = False

    # 实际绑定（WAITING_ANALYSIS/WAITING_BINDING 阶段为 None）
    # 一旦创建第一个 Attempt 后禁止修改
    analysis_id: str | None = None
    bound_source_snapshot_id: str | None = None
    analysis_projection_version: int | None = None

    correlation_config_digest: str = ""
    matcher_version: str = "v1"
    normalization_version: str = "v1"
    supersedes_correlation_run_id: str | None = None

    source_alignment_status: SourceAlignmentStatus = SourceAlignmentStatus.UNVERIFIED
    status: CorrelationRunStatus = CorrelationRunStatus.WAITING_ANALYSIS
    active_attempt_id: str | None = None  # FK → correlation_attempts

    # MISMATCHED override 审计
    source_mismatch_overridden: bool = False
    source_mismatch_override_by: str | None = None
    source_mismatch_override_at: str | None = None
    source_mismatch_override_reason: str | None = None

    started_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = ""


# ── CorrelationAttempt ───────────────────────────────────────


@dataclass
class CorrelationAttempt:
    """每次关联执行记录。冻结白盒输入，禁止跨归属串联。"""

    correlation_attempt_id: str  # PK
    correlation_run_id: str  # FK → correlation_runs (组合 FK)
    attempt_number: int

    # 冻结的白盒输入（不可变）
    analysis_id: str
    source_snapshot_id: str
    analysis_projection_version: int
    matcher_version: str
    normalization_version: str
    correlation_config_digest: str

    status: AttemptStatus = AttemptStatus.RUNNING
    evidence_completeness: EvidenceCompleteness = EvidenceCompleteness.COMPLETE

    # 租约（崩溃恢复）
    lease_owner: str | None = None
    heartbeat_at: str | None = None
    lease_expires_at: str | None = None

    started_at: str = ""
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = ""


# ── HttpRequestEvidence ──────────────────────────────────────


@dataclass
class HttpRequestEvidence:
    """黑盒执行期间捕获的单条 HTTP 请求证据。"""

    request_evidence_id: str  # PK
    blackbox_run_id: str  # FK → blackbox_runs
    task_id: str
    step_execution_id: str | None  # {blackbox_run_id}:step:{idx}:attempt:{n}
    step_attempt: int = 1
    request_sequence: int = 0
    http_method: str = ""  # UPPER
    normalized_path: str = ""
    display_path: str = ""
    origin: str = ""
    resource_type: str = "other"
    endpoint_match_eligibility: CorrelationEligibility = CorrelationEligibility.CONFIRMED_ELIGIBLE
    response_status: int | None = None
    outcome: RequestOutcome = RequestOutcome.COMPLETED
    failure_code: str | None = None
    request_owner: RequestOwner = RequestOwner.FRAME
    response_from_service_worker: bool = False
    page_sequence: int = 0  # Context 内的页面序号
    captured_at: str = ""
    finished_at: str | None = None


# ── EndpointEvidence ─────────────────────────────────────────


@dataclass
class EndpointEvidence:
    """请求与白盒端点的匹配结果。"""

    endpoint_evidence_id: str  # PK
    correlation_run_id: str  # FK → correlation_runs
    correlation_attempt_id: str  # FK → correlation_attempts (组合 FK)
    request_evidence_id: str  # FK → http_request_evidence
    resolution_status: ResolutionStatus = ResolutionStatus.UNMATCHED
    match_strategy: MatchStrategy = MatchStrategy.NONE
    confidence: MatchConfidence = MatchConfidence.UNKNOWN
    matched_endpoint_id: str | None = None
    match_reason_code: str = ""
    matcher_version: str = "v1"
    normalization_version: str = "v1"
    candidate_count: int = 0
    created_at: str = ""


# ── EndpointEvidenceCandidate ────────────────────────────────


@dataclass
class EndpointEvidenceCandidate:
    """歧义匹配的候选端点。"""

    endpoint_evidence_id: str  # FK → endpoint_evidence
    endpoint_id: str  # FK → analysis_endpoints
    candidate_rank: int = 1
    match_strategy: MatchStrategy = MatchStrategy.NONE
    confidence: MatchConfidence = MatchConfidence.UNKNOWN
    reason_code: str = ""
    selected: bool = False  # UNIQUE→True, AMBIGUOUS→全部 False


# ── EndpointEvidenceFlow ─────────────────────────────────────


@dataclass
class EndpointEvidenceFlow:
    """端点证据关联的静态可达调用流。"""

    endpoint_evidence_id: str  # FK → endpoint_evidence
    execution_flow_id: str
    relation_type: str = "STATIC_REACHABLE"  # "ENTRY_POINT" | "STATIC_REACHABLE"
    endpoint_method_snapshot: str | None = None
    endpoint_path_snapshot: str | None = None
    controller_snapshot: str | None = None
    flow_name_snapshot: str | None = None
    source_location_snapshot: str | None = None


# ── FindingEvidence ──────────────────────────────────────────


@dataclass
class FindingEvidence:
    """Finding 关联聚合。"""

    finding_evidence_id: str  # PK
    correlation_attempt_id: str  # FK → correlation_attempts
    finding_id: str  # FK → findings
    best_relation_type: FindingRelationType = FindingRelationType.UNKNOWN
    minimum_call_distance: int | None = None  # NULL=未知
    confirmed_request_count: int = 0
    candidate_request_count: int = 0
    finding_rule_id_snapshot: str | None = None
    finding_location_snapshot: str | None = None


# ── FindingEvidenceLink ──────────────────────────────────────


@dataclass
class FindingEvidenceLink:
    """Finding 关联明细。"""

    finding_evidence_id: str  # FK → finding_evidence
    correlation_attempt_id: str  # FK，确保与 EndpointEvidence 同 attempt
    endpoint_evidence_id: str  # FK → endpoint_evidence
    endpoint_id: str
    execution_flow_id: str | None = None
    relation_type: FindingRelationType = FindingRelationType.UNKNOWN
    call_distance: int | None = None


# ── CorrelationAttemptReason ─────────────────────────────────


@dataclass
class CorrelationAttemptReason:
    """导致 PARTIAL 的原因明细。"""

    correlation_attempt_id: str
    reason_code: PartialReasonCode = PartialReasonCode.CAPTURE_TRUNCATED
    detail: str | None = None


# ── CorrelationAttemptDiagnostic ─────────────────────────────


@dataclass
class CorrelationAttemptDiagnostic:
    """不导致 PARTIAL 的诊断明细。"""

    correlation_attempt_id: str
    diagnostic_code: AttemptDiagnosticCode = AttemptDiagnosticCode.NO_ELIGIBLE_REQUESTS
    detail: str | None = None


# ── CaptureQuality ───────────────────────────────────────────


@dataclass
class CaptureQuality:
    """采集质量统计。"""

    blackbox_run_id: str = ""
    total_observed: int = 0
    accepted_started: int = 0
    persisted_count: int = 0
    filtered_by_resource_type: int = 0
    filtered_cross_origin: int = 0
    filtered_by_method: int = 0
    filtered_websocket_count: int = 0
    filtered_path_too_long: int = 0
    dropped_pending_limit: int = 0
    dropped_run_limit: int = 0
    dropped_writer_queue_limit: int = 0
    writer_retry_count: int = 0
    writer_failed_batch_count: int = 0
    persistence_failed: int = 0
    truncated: bool = False
    truncation_reason: str | None = None
    updated_at: str = ""


# ── PathMapping ──────────────────────────────────────────────


@dataclass
class PathMapping:
    """网关前缀映射配置。"""

    strip_prefixes: list[str] = field(default_factory=list)
    prepend_prefix: str = ""
    context_path: str = ""


# ── CorrelationSummary ───────────────────────────────────────


@dataclass
class CorrelationSummary:
    """关联汇总指标。"""

    correlation_run_id: str = ""
    status: str = ""
    source_alignment_status: str = ""

    captured_request_count: int = 0
    correlatable_request_count: int = 0
    confirmed_matched_request_count: int = 0
    ambiguous_request_count: int = 0
    method_mismatch_candidate_count: int = 0
    unmatched_request_count: int = 0

    total_endpoint_count: int = 0
    confirmed_touched_endpoint_count: int = 0
    candidate_touched_endpoint_count: int = 0
    uncovered_endpoint_count: int = 0
    attempted_evidence_count: int = 0

    total_finding_count: int = 0
    confirmed_related_finding_count: int = 0
    candidate_related_finding_count: int = 0
    unrelated_finding_count: int = 0

    cross_origin_filtered_count: int = 0
    resource_filtered_count: int = 0
    dropped_request_count: int = 0
    failed_capture_count: int = 0

    evidence_completeness: str = "COMPLETE"
    matcher_version: str = "v1"
    normalization_version: str = "v1"


# ── 内部捕获结构（BrowserSession 中使用）────────────────────


class _CapturedRequest:
    """Playwright 事件处理期间的内部请求记录。"""

    __slots__ = (
        "sequence",
        "step_execution_id",
        "step_attempt",
        "page_sequence",
        "method",
        "origin",
        "normalized_path",
        "display_path",
        "resource_type",
        "request_owner",
        "path_too_long",
        "response_status",
        "response_from_service_worker",
        "outcome",
        "failure_code",
        "endpoint_match_eligibility",
        "started_at",
        "finished_at",
    )

    def __init__(
        self,
        *,
        sequence: int,
        step_execution_id: str | None,
        step_attempt: int,
        page_sequence: int,
        method: str,
        origin: str,
        normalized_path: str,
        display_path: str,
        resource_type: str,
        request_owner: str,
        path_too_long: bool = False,
        started_at: str = "",
    ) -> None:
        self.sequence = sequence
        self.step_execution_id = step_execution_id
        self.step_attempt = step_attempt
        self.page_sequence = page_sequence
        self.method = method
        self.origin = origin
        self.normalized_path = normalized_path
        self.display_path = display_path
        self.resource_type = resource_type
        self.request_owner = request_owner
        self.path_too_long = path_too_long
        self.response_status: int | None = None
        self.response_from_service_worker: bool = False
        self.outcome: RequestOutcome = RequestOutcome.COMPLETED
        self.failure_code: str | None = None
        self.endpoint_match_eligibility: CorrelationEligibility = (
            CorrelationEligibility.CONFIRMED_ELIGIBLE
        )
        self.started_at = started_at
        self.finished_at: str | None = None
