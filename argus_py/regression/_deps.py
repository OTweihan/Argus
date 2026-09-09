"""RegressionService 组合依赖面（可维护性 M3）。

仅供 Mixin 静态类型与文档；运行时属性由 ``RegressionService.__init__`` 注入，
交叉方法由门面 / 其它 Mixin 经 MRO 提供。

**风格定调（本仓大服务拆分）**：

- 优先 **Mixin 组合 + 共享 Protocol 依赖面**（本模块）；
- 交叉方法用 ``TYPE_CHECKING`` 声明，**禁止**运行时 ``NotImplementedError`` stub；
- 各 Mixin 只注解**自己实际使用**的注入字段；
- 不要单独实例化 Mixin；包外只依赖 ``application.RegressionService``。

M4 ``WhiteboxRunner`` 已沿用 Mixin 风格（``JobPollMixin``）；成功持久化为共享函数模块
（``result_persist``，供 runner + recovery），非第三种门面风格。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from argus_py.infra.queue import TaskQueue
    from argus_py.regression.models import RegressionRun
    from argus_py.task.lifecycle import TaskLifecycleService
    from argus_py.task.storage import TaskSQLiteStorage


class RegressionServiceDeps(Protocol):
    """完整组合面：注入依赖 + 跨 Mixin 交叉方法。"""

    _storage: TaskSQLiteStorage
    _lifecycle: TaskLifecycleService
    _queue: TaskQueue
    _resolve_create_params: Callable[..., dict[str, Any]]
    _publish: Callable[[str, str, dict[str, Any]], None]

    def _require_run(self, run_id: str) -> RegressionRun: ...

    def _maybe_finalize(self, run_id: str) -> None: ...
