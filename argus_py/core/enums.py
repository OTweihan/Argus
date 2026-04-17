"""Application-wide enumerations."""

from enum import Enum


class TaskType(str, Enum):
    """Task execution types."""

    BLACKBOX = "blackbox"
    WHITEBOX = "whitebox"


class TaskStatus(str, Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ActionType(str, Enum):
    """Browser action types."""

    GOTO = "goto"
    CLICK = "click"
    FILL = "fill"
    PRESS = "press"
    SELECT = "select"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    SNAPSHOT = "snapshot"
    ASSERT = "assert"


class FindingSeverity(str, Enum):
    """Finding severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingType(str, Enum):
    """Finding categorization."""

    FUNCTIONAL = "functional"
    VISUAL = "visual"
    PERFORMANCE = "performance"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    ERROR = "error"
