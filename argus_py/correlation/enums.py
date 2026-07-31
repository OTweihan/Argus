"""阶段三：黑白盒关联 — 枚举定义。"""

from __future__ import annotations

from enum import Enum


class ResolutionStatus(str, Enum):
    """匹配解析结果（单值和歧义是互斥状态）。"""

    UNIQUE = "UNIQUE"  # 唯一匹配
    AMBIGUOUS = "AMBIGUOUS"  # 多个候选
    UNMATCHED = "UNMATCHED"  # 无候选


class MatchStrategy(str, Enum):
    """匹配方式（与解析结果独立）。"""

    EXACT = "EXACT"  # HTTP 方法 + 精确路径
    TEMPLATE = "TEMPLATE"  # HTTP 方法 + 路径模板
    PATH_ONLY = "PATH_ONLY"  # 仅路径匹配（方法不同），UI 层称 METHOD_MISMATCH_CANDIDATE
    NONE = "NONE"  # 未匹配时


class MatchConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class SourceAlignmentStatus(str, Enum):
    """源码版本一致性状态。"""

    VERIFIED = "VERIFIED"  # 部署侧可证明的 commit 一致性
    USER_DECLARED = "USER_DECLARED"  # 仅用户声明，无部署侧证据
    UNVERIFIED = "UNVERIFIED"  # 未提供任何版本信息
    MISMATCHED = "MISMATCHED"  # 已确认版本不一致


class CorrelationRunStatus(str, Enum):
    WAITING_ANALYSIS = "WAITING_ANALYSIS"  # 没有符合条件的已完成白盒分析
    WAITING_BINDING = "WAITING_BINDING"  # 有多个候选，需用户选择
    WAITING_BLACKBOX = "WAITING_BLACKBOX"  # 等待黑盒执行完成
    BLOCKED = "BLOCKED"  # 版本不一致、安全策略或配置禁止
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    STALE = "STALE"


class AttemptStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class FindingRelationType(str, Enum):
    """白盒 Finding 与黑盒证据的关联类型。"""

    DIRECT_HANDLER = "DIRECT_HANDLER"  # Finding 位于端点处理方法内
    STATIC_REACHABLE = "STATIC_REACHABLE"  # 静态调用可达
    FLOW_MEMBER = "FLOW_MEMBER"  # 在执行流中
    UNKNOWN = "UNKNOWN"


class RequestOutcome(str, Enum):
    COMPLETED = "COMPLETED"  # 网络层正常结束（response_status 判断业务成功/失败）
    NETWORK_FAILED = "NETWORK_FAILED"  # requestfailed
    ABANDONED = "ABANDONED"  # flush 时未完成的 pending


class CorrelationEligibility(str, Enum):
    """端点匹配资格。数据库只存这三种；过滤项仅作为 CaptureQuality 统计。"""

    CONFIRMED_ELIGIBLE = "CONFIRMED_ELIGIBLE"  # 参与匹配，可计入 confirmed
    ATTEMPT_ONLY = "ATTEMPT_ONLY"  # 参与匹配，不计入 confirmed
    EXCLUDED_SW_CACHE = "EXCLUDED_SW_CACHE"  # 不参与后端端点匹配


class EvidenceCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class RequestOwner(str, Enum):
    FRAME = "FRAME"
    SERVICE_WORKER = "SERVICE_WORKER"


class PartialReasonCode(str, Enum):
    """导致 PARTIAL 的原因。"""

    CAPTURE_TRUNCATED = "CAPTURE_TRUNCATED"
    REQUEST_PERSISTENCE_FAILED = "REQUEST_PERSISTENCE_FAILED"
    WHITEBOX_PARTIAL = "WHITEBOX_PARTIAL"
    SOURCE_MISMATCH_OVERRIDE = "SOURCE_MISMATCH_OVERRIDE"


class AttemptDiagnosticCode(str, Enum):
    """不导致 PARTIAL 的诊断信息。"""

    REGEX_CONSTRAINT_NOT_PORTABLE = "REGEX_CONSTRAINT_NOT_PORTABLE"
    REGEX_COMPILE_FAILED_FALLBACK = "REGEX_COMPILE_FAILED_FALLBACK"
    NO_ELIGIBLE_REQUESTS = "NO_ELIGIBLE_REQUESTS"
    PATH_MAPPING_APPLIED = "PATH_MAPPING_APPLIED"


class BlackboxRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
