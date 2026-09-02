"""regression_cases / regression_runs / regression_run_items 表读写。

含批次状态 CAS 推进、基线切换（部分唯一索引兜底）与崩溃恢复扫描。
行映射保持在本模块内（表为回归子域私有，无跨模块复用需求）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from argus_py.core.constants import utc_now_iso as _utc_now_iso
from argus_py.core.enums import TaskType
from argus_py.infra.db import DbPool
from argus_py.regression.enums import (
    REGRESSION_TERMINAL_RUN_STATUSES,
    RegressionGateResult,
    RegressionItemStatus,
    RegressionRunStatus,
    RegressionTriggerSource,
)
from argus_py.regression.models import RegressionCase, RegressionRun, RegressionRunItem

_CASE_COLUMNS = (
    "case_id",
    "project_id",
    "name",
    "task_type",
    "goal",
    "start_url",
    "max_steps",
    "timeout_seconds",
    "capture_screenshots",
    "parameters_json",
    "whitebox_config_json",
    "enabled",
    "display_order",
    "created_at",
    "updated_at",
)

_RUN_COLUMNS = (
    "run_id",
    "project_id",
    "trigger_source",
    "triggered_by",
    "baseline_run_id",
    "status",
    "gate_result",
    "summary_json",
    "is_baseline",
    "error_code",
    "error_message",
    "started_at",
    "completed_at",
    "created_at",
)

_ITEM_COLUMNS = (
    "item_id",
    "run_id",
    "case_id",
    "case_name",
    "display_order",
    "case_snapshot_json",
    "task_id",
    "status",
    "finding_count",
    "error_code",
    "error_message",
    "created_at",
)


class BaselineConflictError(RuntimeError):
    """并发设置基线触发部分唯一索引冲突（应用层转 409）。"""


def _row_to_case(row: dict[str, Any]) -> RegressionCase:
    return RegressionCase(
        case_id=row["case_id"],
        project_id=row["project_id"],
        name=row["name"],
        task_type=TaskType(row.get("task_type", TaskType.BLACKBOX.value)),
        goal=row.get("goal", ""),
        start_url=row.get("start_url"),
        max_steps=int(row.get("max_steps", 0)),
        timeout_seconds=int(row.get("timeout_seconds", 0)),
        capture_screenshots=bool(row.get("capture_screenshots", True)),
        parameters_json=row.get("parameters_json", "{}"),
        whitebox_config_json=row.get("whitebox_config_json"),
        enabled=bool(row.get("enabled", True)),
        display_order=int(row.get("display_order", 0)),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def _row_to_run(row: dict[str, Any]) -> RegressionRun:
    gate = row.get("gate_result")
    return RegressionRun(
        run_id=row["run_id"],
        project_id=row["project_id"],
        trigger_source=_parse_trigger(row.get("trigger_source")),
        triggered_by=row.get("triggered_by"),
        baseline_run_id=row.get("baseline_run_id"),
        status=RegressionRunStatus(row.get("status", RegressionRunStatus.PENDING.value)),
        gate_result=RegressionGateResult(gate) if gate else None,
        summary_json=row.get("summary_json", "{}"),
        is_baseline=bool(row.get("is_baseline", False)),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        created_at=row.get("created_at", ""),
    )


def _parse_trigger(value: Any) -> RegressionTriggerSource:
    try:
        return RegressionTriggerSource(value)
    except ValueError:
        return RegressionTriggerSource.API


def _row_to_item(row: dict[str, Any]) -> RegressionRunItem:
    return RegressionRunItem(
        item_id=row["item_id"],
        run_id=row["run_id"],
        case_id=row["case_id"],
        case_name=row.get("case_name", ""),
        display_order=int(row.get("display_order", 0)),
        case_snapshot_json=row.get("case_snapshot_json", "{}"),
        task_id=row.get("task_id"),
        status=RegressionItemStatus(row.get("status", RegressionItemStatus.PENDING.value)),
        finding_count=(int(row["finding_count"]) if row.get("finding_count") is not None else None),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        created_at=row.get("created_at", ""),
    )


class RegressionRepository:
    """回归用例 / 批次 / 批次项存储与状态机推进。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    # ══════════════════════════════════════════════════════════
    # RegressionCase
    # ══════════════════════════════════════════════════════════

    def create_case(self, case: RegressionCase) -> RegressionCase:
        placeholders = ", ".join(["?"] * len(_CASE_COLUMNS))
        columns = ", ".join(_CASE_COLUMNS)
        values = (
            case.case_id,
            case.project_id,
            case.name,
            case.task_type.value,
            case.goal,
            case.start_url,
            case.max_steps,
            case.timeout_seconds,
            int(case.capture_screenshots),
            case.parameters_json,
            case.whitebox_config_json,
            int(case.enabled),
            case.display_order,
            case.created_at,
            case.updated_at,
        )
        with self._pool.tx() as conn:
            conn.execute(
                f"INSERT INTO regression_cases ({columns}) VALUES ({placeholders})", values
            )
        return case

    def get_case(self, case_id: str) -> RegressionCase | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM regression_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_case(dict(row))

    def list_cases(self, project_id: str, *, enabled_only: bool = False) -> list[RegressionCase]:
        query = "SELECT * FROM regression_cases WHERE project_id = ?"
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY display_order ASC, created_at ASC"
        with self._pool.ro_conn() as conn:
            rows = conn.execute(query, (project_id,)).fetchall()
        return [_row_to_case(dict(r)) for r in rows]

    def update_case(self, case_id: str, fields: dict[str, Any]) -> None:
        """窄更新用例字段；字段名必须是 regression_cases 列。"""
        allowed = set(_CASE_COLUMNS) - {"case_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _utc_now_iso()
        assignments = ", ".join(f"{col} = ?" for col in updates)
        params = (*updates.values(), case_id)
        with self._pool.tx() as conn:
            conn.execute(f"UPDATE regression_cases SET {assignments} WHERE case_id = ?", params)

    def delete_case(self, case_id: str) -> None:
        with self._pool.tx() as conn:
            conn.execute("DELETE FROM regression_cases WHERE case_id = ?", (case_id,))

    # ══════════════════════════════════════════════════════════
    # RegressionRun
    # ══════════════════════════════════════════════════════════

    def create_run_with_items(self, run: RegressionRun, items: list[RegressionRunItem]) -> None:
        """单事务写入批次与全部批次项（保证批次不会出现半初始化状态）。"""
        run_columns = ", ".join(_RUN_COLUMNS)
        run_placeholders = ", ".join(["?"] * len(_RUN_COLUMNS))
        item_columns = ", ".join(_ITEM_COLUMNS)
        item_placeholders = ", ".join(["?"] * len(_ITEM_COLUMNS))
        with self._pool.tx() as conn:
            conn.execute(
                f"INSERT INTO regression_runs ({run_columns}) VALUES ({run_placeholders})",
                (
                    run.run_id,
                    run.project_id,
                    run.trigger_source.value,
                    run.triggered_by,
                    run.baseline_run_id,
                    run.status.value,
                    run.gate_result.value if run.gate_result else None,
                    run.summary_json,
                    int(run.is_baseline),
                    run.error_code,
                    run.error_message,
                    run.started_at,
                    run.completed_at,
                    run.created_at,
                ),
            )
            for item in items:
                conn.execute(
                    f"INSERT INTO regression_run_items ({item_columns}) "
                    f"VALUES ({item_placeholders})",
                    (
                        item.item_id,
                        item.run_id,
                        item.case_id,
                        item.case_name,
                        item.display_order,
                        item.case_snapshot_json,
                        item.task_id,
                        item.status.value,
                        item.finding_count,
                        item.error_code,
                        item.error_message,
                        item.created_at,
                    ),
                )

    def get_run(self, run_id: str) -> RegressionRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM regression_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_run(dict(row))

    def list_runs(
        self,
        project_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        status: RegressionRunStatus | None = None,
    ) -> tuple[list[RegressionRun], int]:
        conditions = ["project_id = ?"]
        params: list[Any] = [project_id]
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        where = " AND ".join(conditions)
        with self._pool.ro_conn() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM regression_runs WHERE {where}", params
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM regression_runs WHERE {where} "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        total = total_row["cnt"] if total_row else 0
        return [_row_to_run(dict(r)) for r in rows], int(total)

    def mark_running(self, run_id: str) -> bool:
        """CAS pending → running（提交完成时调用）。"""
        with self._pool.tx() as conn:
            cursor = conn.execute(
                "UPDATE regression_runs SET status = 'running', started_at = ? "
                "WHERE run_id = ? AND status = 'pending'",
                (_utc_now_iso(), run_id),
            )
        return cursor.rowcount == 1

    def finalize_run(
        self,
        run_id: str,
        *,
        status: RegressionRunStatus,
        gate_result: RegressionGateResult | None,
        summary_json: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """CAS pending/running → 终态（幂等；已终态的批次再次 finalize 返回 False）。

        允许从 pending 直达终态：队列满载 fail-fast 发生在提交阶段（批次仍为
        pending），崩溃恢复也可能对未及 mark_running 的批次直接收尾。
        """
        with self._pool.tx() as conn:
            cursor = conn.execute(
                """UPDATE regression_runs
                   SET status = ?, gate_result = ?, summary_json = ?,
                       error_code = ?, error_message = ?, completed_at = ?
                   WHERE run_id = ? AND status IN ('pending', 'running')""",
                (
                    status.value,
                    gate_result.value if gate_result else None,
                    summary_json,
                    error_code,
                    error_message,
                    _utc_now_iso(),
                    run_id,
                ),
            )
        return cursor.rowcount == 1

    def update_error(self, run_id: str, error_code: str, error_message: str) -> None:
        """非终态批次的错误信息追加（不改变状态）。"""
        with self._pool.tx() as conn:
            conn.execute(
                "UPDATE regression_runs SET error_code = ?, error_message = ? WHERE run_id = ?",
                (error_code, error_message, run_id),
            )

    # ── 基线 ─────────────────────────────────────────────────

    def set_baseline(self, project_id: str, run_id: str) -> bool:
        """将成功批次设为项目基线（事务内先清旧后置新）。

        目标批次必须属于该项目且已 completed，否则返回 False。
        并发设置不同批次时，后写方触发部分唯一索引
        uq_regression_baseline_per_project → 抛 :class:`BaselineConflictError`，
        由应用层转换为 409。
        """
        with self._pool.tx() as conn:
            target = conn.execute(
                "SELECT status FROM regression_runs WHERE run_id = ? AND project_id = ?",
                (run_id, project_id),
            ).fetchone()
            if target is None or target["status"] != RegressionRunStatus.COMPLETED.value:
                return False
            conn.execute(
                "UPDATE regression_runs SET is_baseline = 0 "
                "WHERE project_id = ? AND is_baseline = 1",
                (project_id,),
            )
            try:
                conn.execute(
                    "UPDATE regression_runs SET is_baseline = 1 WHERE run_id = ?",
                    (run_id,),
                )
            except sqlite3.IntegrityError as exc:
                raise BaselineConflictError(
                    f"项目 {project_id} 已被并发设置为其他基线批次。"
                ) from exc
        return True

    def get_baseline(self, project_id: str) -> RegressionRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM regression_runs WHERE project_id = ? AND is_baseline = 1",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_run(dict(row))

    def clear_baseline_if_invalid(self, project_id: str) -> None:
        """基线指向的批次不再是终态时清除基线标记（防御性，当前无此路径）。"""
        with self._pool.tx() as conn:
            conn.execute(
                """UPDATE regression_runs SET is_baseline = 0
                   WHERE project_id = ? AND is_baseline = 1
                     AND status NOT IN ('completed', 'failed', 'cancelled')""",
                (project_id,),
            )

    # ══════════════════════════════════════════════════════════
    # RegressionRunItem
    # ══════════════════════════════════════════════════════════

    def get_items(self, run_id: str) -> list[RegressionRunItem]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM regression_run_items WHERE run_id = ? "
                "ORDER BY display_order ASC, created_at ASC",
                (run_id,),
            ).fetchall()
        return [_row_to_item(dict(r)) for r in rows]

    def get_item_by_task_id(self, task_id: str) -> RegressionRunItem | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM regression_run_items WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_item(dict(row))

    def attach_task(self, item_id: str, task_id: str) -> None:
        with self._pool.tx() as conn:
            conn.execute(
                "UPDATE regression_run_items SET task_id = ? WHERE item_id = ?",
                (task_id, item_id),
            )

    def attach_tasks(self, pairs: list[tuple[str, str]]) -> None:
        """批量回填 item→task_id（单事务）。"""
        if not pairs:
            return
        with self._pool.tx() as conn:
            conn.executemany(
                "UPDATE regression_run_items SET task_id = ? WHERE item_id = ?",
                [(task_id, item_id) for item_id, task_id in pairs],
            )

    def update_item_status(
        self,
        item_id: str,
        status: RegressionItemStatus,
        *,
        finding_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.update_item_statuses(
            [
                {
                    "item_id": item_id,
                    "status": status,
                    "finding_count": finding_count,
                    "error_code": error_code,
                    "error_message": error_message,
                }
            ]
        )

    def update_item_statuses(self, updates: list[dict[str, Any]]) -> None:
        """批量更新批次项状态（单事务，减少 abort/cancel 的 N 次往返）。

        每项字典键：``item_id``、``status``（RegressionItemStatus）、可选
        ``finding_count`` / ``error_code`` / ``error_message``。
        """
        if not updates:
            return
        with self._pool.tx() as conn:
            for entry in updates:
                item_id = str(entry["item_id"])
                status = entry["status"]
                status_value = status.value if hasattr(status, "value") else str(status)
                sets = ["status = ?"]
                params: list[Any] = [status_value]
                if entry.get("finding_count") is not None:
                    sets.append("finding_count = ?")
                    params.append(entry["finding_count"])
                sets.append("error_code = ?")
                params.append(entry.get("error_code"))
                sets.append("error_message = ?")
                params.append(entry.get("error_message"))
                params.append(item_id)
                conn.execute(
                    f"UPDATE regression_run_items SET {', '.join(sets)} WHERE item_id = ?",
                    params,
                )

    def count_item_statuses(self, run_id: str) -> dict[str, int]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM regression_run_items "
                "WHERE run_id = ? GROUP BY status",
                (run_id,),
            ).fetchall()
        return {row["status"]: int(row["cnt"]) for row in rows}

    # ══════════════════════════════════════════════════════════
    # 崩溃恢复扫描
    # ══════════════════════════════════════════════════════════

    def list_unfinished_runs(self) -> list[RegressionRun]:
        """返回全部非终态批次（启动恢复用）。"""
        placeholders = ", ".join("?" for _ in REGRESSION_TERMINAL_RUN_STATUSES)
        terminal_values = [s.value for s in REGRESSION_TERMINAL_RUN_STATUSES]
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM regression_runs WHERE status NOT IN ({placeholders})",
                terminal_values,
            ).fetchall()
        return [_row_to_run(dict(r)) for r in rows]
