"""应用级枚举。"""

from enum import Enum


class TaskType(str, Enum):
    """任务类型。"""

    BLACKBOX = "blackbox"
    WHITEBOX = "whitebox"


class TaskStatus(str, Enum):
    """任务生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ActionType(str, Enum):
    """浏览器动作类型。"""

    GOTO = "goto"
    CLICK = "click"
    FILL = "fill"
    PRESS = "press"
    SELECT = "select"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    SNAPSHOT = "snapshot"
    ASSERT = "assert"


class StepResult(str, Enum):
    """步骤执行结果。"""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class FindingSeverity(str, Enum):
    """问题严重级别。"""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingType(str, Enum):
    """问题分类。"""

    FUNCTIONAL = "functional"
    VISUAL = "visual"
    PERFORMANCE = "performance"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    ERROR = "error"
