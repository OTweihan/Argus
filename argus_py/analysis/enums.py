"""分析执行领域 — 枚举定义。

AnalysisRunStatus：执行生命周期状态
CompletenessStatus：结果完整性（仅 SUCCEEDED 时评估）
QualityIssueCode / QualityIssueLevel：质量问题分类与等级
RuleCategory / AnalysisConfidence：规则语义（Java 唯一来源）
AnalysisScope：首期只开放 ALL / MODULES
"""

from __future__ import annotations

from enum import Enum


class AnalysisRunStatus(str, Enum):
    """分析执行生命周期状态。"""

    QUEUED = "QUEUED"
    SUBMITTING = "SUBMITTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    STOPPED_WAITING = "STOPPED_WAITING"

    @property
    def is_terminal(self) -> bool:
        """是否为终态。"""
        return self in (
            AnalysisRunStatus.SUCCEEDED,
            AnalysisRunStatus.FAILED,
            AnalysisRunStatus.TIMED_OUT,
            AnalysisRunStatus.CANCELLED,
            AnalysisRunStatus.STOPPED_WAITING,
        )


# 合法状态迁移表
_VALID_TRANSITIONS: dict[AnalysisRunStatus, set[AnalysisRunStatus]] = {
    AnalysisRunStatus.QUEUED: {AnalysisRunStatus.SUBMITTING, AnalysisRunStatus.CANCELLED},
    AnalysisRunStatus.SUBMITTING: {
        AnalysisRunStatus.RUNNING,
        AnalysisRunStatus.FAILED,
        AnalysisRunStatus.CANCELLED,
    },
    AnalysisRunStatus.RUNNING: {
        AnalysisRunStatus.SUCCEEDED,
        AnalysisRunStatus.FAILED,
        AnalysisRunStatus.TIMED_OUT,
        AnalysisRunStatus.CANCELLED,
        AnalysisRunStatus.STOPPED_WAITING,
    },
    AnalysisRunStatus.SUCCEEDED: set(),
    AnalysisRunStatus.FAILED: set(),
    AnalysisRunStatus.TIMED_OUT: set(),
    AnalysisRunStatus.CANCELLED: set(),
    AnalysisRunStatus.STOPPED_WAITING: set(),
}


def is_valid_transition(
    current: AnalysisRunStatus,
    target: AnalysisRunStatus,
) -> bool:
    """校验状态迁移是否合法。"""
    return target in _VALID_TRANSITIONS.get(current, set())


class CompletenessStatus(str, Enum):
    """分析结果完整性。仅当 runStatus=SUCCEEDED 时评估。"""

    NOT_EVALUATED = "NOT_EVALUATED"
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class RuleCategory(str, Enum):
    """规则类别 — Java 分析器是唯一来源。"""

    SECURITY = "SECURITY"
    BUG = "BUG"
    CODE_SMELL = "CODE_SMELL"
    PERFORMANCE = "PERFORMANCE"
    STYLE = "STYLE"
    UNKNOWN = "UNKNOWN"


class AnalysisConfidence(str, Enum):
    """分析置信度 — 命名与阶段三匹配置信度区分。"""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class AnalysisScope(str, Enum):
    """分析范围。首期只开放 ALL 和 MODULES。"""

    ALL = "ALL"
    MODULES = "MODULES"


class QualityIssueCode(str, Enum):
    """质量问题代码 — 结构化错误码，前端据此显示图标和操作提示。"""

    NO_ELIGIBLE_SOURCE_FILES = "NO_ELIGIBLE_SOURCE_FILES"
    MODULE_PARSE_PARTIAL_FAILURE = "MODULE_PARSE_PARTIAL_FAILURE"
    CLASSPATH_DEGRADED = "CLASSPATH_DEGRADED"
    CLASSPATH_UNAVAILABLE = "CLASSPATH_UNAVAILABLE"
    CALL_RESOLUTION_LOW = "CALL_RESOLUTION_LOW"
    PARTIAL_RESULT = "PARTIAL_RESULT"
    ZERO_FINDINGS = "ZERO_FINDINGS"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"


class QualityIssueLevel(str, Enum):
    """质量问题等级。"""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# QualityIssueCode → 默认等级 + 完整性影响 中央映射表
_QUALITY_ISSUE_RULES: dict[
    QualityIssueCode, tuple[QualityIssueLevel, CompletenessStatus | None]
] = {
    QualityIssueCode.NO_ELIGIBLE_SOURCE_FILES: (
        QualityIssueLevel.ERROR,
        CompletenessStatus.UNAVAILABLE,
    ),
    QualityIssueCode.MODULE_PARSE_PARTIAL_FAILURE: (
        QualityIssueLevel.WARNING,
        CompletenessStatus.DEGRADED,
    ),
    QualityIssueCode.CLASSPATH_DEGRADED: (
        QualityIssueLevel.WARNING,
        CompletenessStatus.DEGRADED,
    ),
    QualityIssueCode.CLASSPATH_UNAVAILABLE: (
        QualityIssueLevel.WARNING,
        None,  # 根据上下文可能 DEGRADED 或 UNAVAILABLE
    ),
    QualityIssueCode.CALL_RESOLUTION_LOW: (
        QualityIssueLevel.WARNING,
        CompletenessStatus.DEGRADED,
    ),
    QualityIssueCode.PARTIAL_RESULT: (
        QualityIssueLevel.WARNING,
        CompletenessStatus.DEGRADED,
    ),
    QualityIssueCode.ZERO_FINDINGS: (
        QualityIssueLevel.INFO,
        None,  # 合法结果，不影响完整性
    ),
    QualityIssueCode.SCHEMA_VERSION_MISMATCH: (
        QualityIssueLevel.ERROR,
        None,  # 应在执行层面拒绝，不产生 QualityIssue
    ),
}


def get_quality_issue_defaults(
    code: QualityIssueCode,
) -> tuple[QualityIssueLevel, CompletenessStatus | None]:
    """返回 QualityIssueCode 的默认等级和完整性影响。"""
    return _QUALITY_ISSUE_RULES.get(code, (QualityIssueLevel.WARNING, None))
