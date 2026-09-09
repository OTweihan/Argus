"""回归服务内部共享常量、映射与错误类型。

**包内**供 case / run / finalization / recovery / application 引用。

**包外稳定入口**（请只走这里，不要 import 本模块）::

    from argus_py.regression.application import (
        REGRESSION_PARAMS_KEY,
        RegressionError,
        RegressionService,
    )

``REGRESSION_PARAMS_KEY`` / ``RegressionError`` 虽定义于此，但是经 ``application``
再导出的公开符号；``_common`` 路径本身属于实现细节，可随拆分调整。
"""

from __future__ import annotations

from typing import Any

from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import ArgusError
from argus_py.regression.enums import RegressionItemStatus
from argus_py.regression.models import RegressionRunItem

# 子任务名称前缀：任务列表中可直接识别回归来源
_REGRESSION_NAME_PREFIX = "[回归] "
# 子任务 parameters 中携带的回归关联标识键（经 application 再导出）
REGRESSION_PARAMS_KEY = "regression"

_TASK_TO_ITEM_STATUS: dict[str, RegressionItemStatus] = {
    TaskStatus.PENDING.value: RegressionItemStatus.PENDING,
    TaskStatus.RUNNING.value: RegressionItemStatus.RUNNING,
    TaskStatus.PAUSED.value: RegressionItemStatus.RUNNING,
    TaskStatus.COMPLETED.value: RegressionItemStatus.COMPLETED,
    TaskStatus.FAILED.value: RegressionItemStatus.FAILED,
    TaskStatus.TIMEOUT.value: RegressionItemStatus.TIMEOUT,
    TaskStatus.CANCELLED.value: RegressionItemStatus.CANCELLED,
}

_ITEM_TERMINAL_STATUSES: frozenset[RegressionItemStatus] = frozenset(
    {
        RegressionItemStatus.COMPLETED,
        RegressionItemStatus.FAILED,
        RegressionItemStatus.TIMEOUT,
        RegressionItemStatus.CANCELLED,
        RegressionItemStatus.SKIPPED,
    }
)


class RegressionError(ArgusError):
    """回归业务错误，携带稳定错误码与 HTTP 语义。

    对外请 ``from argus_py.regression.application import RegressionError``。
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.details = details or {}


class _QueueFullAbort(Exception):
    """提交阶段命中队列容量上限的内部信号。"""


class _BatchCreateInterrupted(Exception):
    """批量创建子任务中途失败；携带已成功创建的 (item, task_id) 供 abort 回收。"""

    def __init__(self, pairs: list[tuple[RegressionRunItem, str]], cause: BaseException) -> None:
        super().__init__(str(cause))
        self.pairs = pairs
        self.cause = cause
