"""回归批次协调应用服务。

线程/协程约定（重要）：
- **async 方法**（``create_run`` / ``cancel_run``）：需要与进程内 TaskQueue
  交互，必须在事件循环上调用；其中同步 SQLite/lifecycle 操作统一经
  ``run_in_thread`` 执行；
- **sync 方法**（用例 CRUD、``handle_task_terminal``、基线管理、恢复扫描、
  查询）：纯 SQLite 操作；API 路由经 ``run_in_thread`` 调用，
  ``handle_task_terminal`` 由 ``TaskLifecycleService`` 的终态回调在任务落盘
  线程内直接调用；TaskRunner 会等待该 IO 工作完成，不在事件循环执行。

批次状态语义：
- ``completed``：批次执行完毕，是否通过质量门禁见 ``gate_result``；
- ``failed``：批次自身失败（队列满载 fail-fast、创建中断、恢复兜底）；
- ``cancelled``：用户显式取消。

实现拆分（可维护性 M3，行为不变）：

- ``_common``：共享常量、状态映射、``RegressionError`` 与内部信号
- ``_deps``：``RegressionServiceDeps`` Protocol（Mixin 静态依赖面）
- ``case_commands``：用例 CRUD + 输入校验
- ``run_commands``：批次创建 / 取消 / 回收
- ``run_finalization``：终态回调、差异门禁、summary
- ``run_recovery``：启动对账恢复
- 本模块：门面组合 + 基线/查询；对外 import 路径不变
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from argus_py.regression._common import (
    REGRESSION_PARAMS_KEY,
    RegressionError,
)
from argus_py.regression.case_commands import CaseCommandsMixin
from argus_py.regression.enums import RegressionRunStatus
from argus_py.regression.models import RegressionRun
from argus_py.regression.run_commands import RunCommandsMixin
from argus_py.regression.run_finalization import RunFinalizationMixin
from argus_py.regression.run_recovery import RunRecoveryMixin
from argus_py.task.repositories.regression_repo import BaselineConflictError

if TYPE_CHECKING:
    from collections.abc import Callable

    from argus_py.infra.queue import TaskQueue
    from argus_py.task.lifecycle import TaskLifecycleService
    from argus_py.task.storage import TaskSQLiteStorage

__all__ = [
    "REGRESSION_PARAMS_KEY",
    "RegressionError",
    "RegressionService",
]


class RegressionService(
    CaseCommandsMixin,
    RunCommandsMixin,
    RunFinalizationMixin,
    RunRecoveryMixin,
):
    """项目级回归闭环编排：用例 → 批次 → 终态汇总与门禁。"""

    def __init__(
        self,
        *,
        storage: "TaskSQLiteStorage",
        lifecycle: "TaskLifecycleService",
        queue: "TaskQueue",
        resolve_create_params: "Callable[..., dict[str, Any]]",
        event_publisher: "Callable[[str, str, dict[str, Any]], None] | None" = None,
    ) -> None:
        self._storage = storage
        self._lifecycle = lifecycle
        self._queue = queue
        # TaskApplicationService.resolve_create_params：用例保存时做与任务创建
        # 完全一致的校验与默认值合并（CLI 与 API 共用同一应用服务约束）
        self._resolve_create_params = resolve_create_params
        self._publish = event_publisher or (lambda *args, **kwargs: None)

    # ══════════════════════════════════════════════════════════
    # 基线（sync）
    # ══════════════════════════════════════════════════════════

    def set_baseline(self, run_id: str) -> RegressionRun:
        """将成功批次设为其项目的基线（仅 completed 批次）。"""
        run = self._require_run(run_id)
        if run.status is not RegressionRunStatus.COMPLETED:
            raise RegressionError(
                "BASELINE_ONLY_COMPLETED_BATCH",
                f"只有执行完毕的批次可以设为基线，当前状态：{run.status.value}。",
                http_status=409,
                details={"runId": run_id, "status": run.status.value},
            )
        try:
            ok = self._storage.set_regression_baseline(run.project_id, run_id)
        except BaselineConflictError as exc:
            raise RegressionError(
                "BASELINE_CONFLICT",
                str(exc),
                http_status=409,
                details={"runId": run_id},
            ) from exc
        if not ok:
            raise RegressionError(
                "BASELINE_SET_FAILED",
                f"设置基线失败：批次 {run_id} 不可用或不属于该项目。",
                http_status=409,
                details={"runId": run_id},
            )
        return self._require_run(run_id)

    def get_baseline(self, project_id: str) -> RegressionRun | None:
        return self._storage.get_regression_baseline(project_id)

    # ══════════════════════════════════════════════════════════
    # 查询（sync）
    # ══════════════════════════════════════════════════════════

    def get_run(self, run_id: str) -> RegressionRun:
        return self._require_run(run_id)

    def list_runs(
        self,
        project_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        status: RegressionRunStatus | None = None,
    ) -> tuple[list[RegressionRun], int]:
        return self._storage.list_regression_runs(
            project_id, offset=offset, limit=limit, status=status
        )

    def get_run_items(self, run_id: str) -> list[dict[str, Any]]:
        """批次项列表，附实时任务状态（tasks 表为权威）。"""
        items = self._storage.get_regression_items(run_id)
        task_ids = [item.task_id for item in items if item.task_id]
        # 详情轮询热路径：一次 IN 查询拿全部状态，避免 N 次 SELECT *（含 result_json）。
        status_by_task = self._storage.get_task_statuses(task_ids) if task_ids else {}
        result: list[dict[str, Any]] = []
        for item in items:
            data: dict[str, Any] = {
                "itemId": item.item_id,
                "runId": item.run_id,
                "caseId": item.case_id,
                "caseName": item.case_name,
                "displayOrder": item.display_order,
                "taskId": item.task_id,
                "status": item.status.value,
                "findingCount": item.finding_count,
                "errorCode": item.error_code,
                "errorMessage": item.error_message,
                "createdAt": item.created_at,
                "taskStatus": status_by_task.get(item.task_id) if item.task_id else None,
            }
            result.append(data)
        return result

    def get_run_summary(self, run_id: str) -> dict[str, Any]:
        """返回批次持久化汇总（含差异明细与门禁原因）。"""
        run = self._require_run(run_id)
        try:
            parsed = json.loads(run.summary_json)
        except (TypeError, ValueError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _require_run(self, run_id: str) -> RegressionRun:
        """查询侧共享 helper：门面基线/查询与 RunCommandsMixin 经 MRO 共用。"""
        run = self._storage.get_regression_run(run_id)
        if run is None:
            raise RegressionError(
                "REGRESSION_RUN_NOT_FOUND",
                f"回归批次不存在：{run_id}",
                http_status=404,
                details={"runId": run_id},
            )
        return run
