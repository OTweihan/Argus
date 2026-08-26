"""回归测试闭环枚举。

与 ``argus_py.core.enums`` 分离：回归是独立子域，状态集合由本模块演进，
避免向全局枚举堆叠业务语义（对齐 ``argus_py.correlation.enums`` 先例）。
"""

from __future__ import annotations

from enum import Enum


class RegressionRunStatus(str, Enum):
    """回归批次生命周期状态。

    - pending：批次与批次项已落库，子任务尚未全部提交入队；
    - running：全部启用用例的子任务已提交，等待终态；
    - completed / failed / cancelled：终态（completed 表示批次执行完毕，
      门禁是否通过见 ``gate_result``；failed 表示批次自身失败，如队列满载
      或创建中断）。
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RegressionTriggerSource(str, Enum):
    """批次触发来源。"""

    CONSOLE = "console"
    API = "api"
    CLI = "cli"


class RegressionItemStatus(str, Enum):
    """回归批次项状态（镜像其子任务状态，另加 skipped）。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class RegressionGateResult(str, Enum):
    """质量门禁结论。"""

    PASSED = "passed"
    FAILED = "failed"


class RegressionDiffCategory(str, Enum):
    """问题差异分类（相对基线、按用例匹配后比较）。"""

    ADDED = "added"
    PERSISTENT = "persistent"
    RESOLVED = "resolved"


REGRESSION_TERMINAL_RUN_STATUSES: frozenset[RegressionRunStatus] = frozenset(
    {
        RegressionRunStatus.COMPLETED,
        RegressionRunStatus.FAILED,
        RegressionRunStatus.CANCELLED,
    }
)
"""批次终态集合。"""
