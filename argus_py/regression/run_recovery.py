"""回归批次崩溃恢复（可维护性 M3）。

sync：Worker 启动 reconciliation 调用。
由 ``RegressionService`` 经 Mixin 组合；公开方法名与行为不变。
内部实现模块——请勿单独实例化。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from argus_py.regression._common import (
    _ITEM_TERMINAL_STATUSES,
    _TASK_TO_ITEM_STATUS,
)
from argus_py.regression.enums import RegressionItemStatus, RegressionRunStatus
from argus_py.regression.fingerprint import FINGERPRINT_VERSION
from argus_py.regression.models import RegressionRun

if TYPE_CHECKING:
    from argus_py.task.lifecycle import TaskLifecycleService
    from argus_py.task.storage import TaskSQLiteStorage

logger = logging.getLogger(__name__)


class RunRecoveryMixin:
    """recover_stale_runs 与单批次对账。

    仅组合进 ``RegressionService``；依赖面见 ``_deps.RegressionServiceDeps``。
    """

    # 本 Mixin 实际使用的注入依赖
    _storage: TaskSQLiteStorage
    _lifecycle: TaskLifecycleService

    if TYPE_CHECKING:
        # 交叉方法由 ``RunFinalizationMixin._maybe_finalize`` 提供（无运行时 stub）
        def _maybe_finalize(self, run_id: str) -> None: ...

    def recover_stale_runs(self) -> int:
        """启动恢复：对账非终态批次的批次项并尽量收尾。

        - 批次项无 task_id / 任务行丢失 → cancelled（本应执行而未执行，
          必须让门禁显式失败；skipped 是非阻断状态，会误放行全中断批次）；
        - 子任务仍为非终态（进程重启后内存队列已丢，永远无人执行）→ 取消
          子任务并将批次项置 cancelled；
        - 全部批次项终态后走正常 finalize（差异 + 门禁 + CAS 幂等）。
        返回收尾的批次数。失败不抛出——由调用方记录日志。
        """
        recovered = 0
        try:
            runs = self._storage.list_unfinished_regression_runs()
        except Exception:
            logger.exception("回归批次恢复扫描失败")
            return 0
        for run in runs:
            try:
                if self._recover_one(run):
                    recovered += 1
            except Exception:
                logger.exception("回归批次恢复失败: run=%s", run.run_id)
        return recovered

    def _recover_one(self, run: RegressionRun) -> bool:
        items = self._storage.get_regression_items(run.run_id)
        if not items:
            # 防御：正常路径不可能出现空批次
            self._storage.finalize_regression_run(
                run_id=run.run_id,
                status=RegressionRunStatus.FAILED,
                gate_result=None,
                summary_json=json.dumps({"fingerprintVersion": FINGERPRINT_VERSION}),
                error_code="REGRESSION_RUN_EMPTY",
                error_message="批次没有任何批次项。",
            )
            return True

        # 一次批量取 header，避免恢复路径对每个 item SELECT *（含大字段）。
        header_task_ids = [item.task_id for item in items if item.task_id]
        headers = self._storage.load_task_headers(header_task_ids) if header_task_ids else {}

        for item in items:
            if item.status in _ITEM_TERMINAL_STATUSES:
                continue
            if item.task_id is None:
                self._storage.update_regression_item_status(
                    item.item_id,
                    RegressionItemStatus.CANCELLED,
                    error_code="TASK_MISSING",
                    error_message="进程重启导致批次创建中断，该用例未提交执行。",
                )
                continue
            header = headers.get(item.task_id)
            if header is None:
                self._storage.update_regression_item_status(
                    item.item_id,
                    RegressionItemStatus.CANCELLED,
                    error_code="TASK_DELETED",
                    error_message="子任务已被删除，该用例未产生结果。",
                )
                continue
            task_status = header.get("status")
            mapped = _TASK_TO_ITEM_STATUS.get(str(task_status))
            if mapped in _ITEM_TERMINAL_STATUSES:
                finding_counts = self._storage.count_findings_by_task_ids([item.task_id])
                self._storage.update_regression_item_status(
                    item.item_id,
                    mapped or RegressionItemStatus.SKIPPED,
                    finding_count=finding_counts.get(item.task_id, 0),
                )
                continue
            # 非终态任务在重启后永远不会被执行（队列在内存中）——取消并计为
            # 批次项 cancelled，使门禁显式失败而非静默悬挂。
            try:
                task = self._lifecycle.storage.load(item.task_id)
                self._lifecycle.cancel_task(task)
            except Exception:
                logger.warning(
                    "恢复批次时取消孤儿子任务失败: run=%s task=%s",
                    run.run_id,
                    item.task_id,
                    exc_info=True,
                )
                continue
            self._storage.update_regression_item_status(
                item.item_id,
                RegressionItemStatus.CANCELLED,
                error_code="INTERRUPTED_BY_RESTART",
                error_message="进程重启导致子任务未执行。",
            )

        before = run.status
        self._maybe_finalize(run.run_id)
        after = self._storage.get_regression_run(run.run_id)
        finalized = after is not None and after.status in (
            RegressionRunStatus.COMPLETED,
            RegressionRunStatus.FAILED,
            RegressionRunStatus.CANCELLED,
        )
        logger.info("回归批次恢复: run=%s before=%s finalized=%s", run.run_id, before, finalized)
        return finalized
