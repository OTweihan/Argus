"""BlackboxRun 与采集质量（http_capture_quality）表读写。"""

from __future__ import annotations

from typing import Any

from argus_py.core.constants import utc_now_iso as _utc_now_iso
from argus_py.correlation.models import BlackboxRun, CaptureQuality
from argus_py.infra.db import DbPool
from argus_py.task.repositories.mappers import blackbox_run_to_row, row_to_blackbox_run


class BlackboxRunRepository:
    """blackbox_runs 与 http_capture_quality 表读写。"""

    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def create(self, run: BlackboxRun) -> BlackboxRun:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT INTO blackbox_runs (
                    blackbox_run_id, task_id, attempt, status, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                blackbox_run_to_row(run),
            )
        return run

    def get(self, blackbox_run_id: str) -> BlackboxRun | None:
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM blackbox_runs WHERE blackbox_run_id = ?",
                (blackbox_run_id,),
            ).fetchone()
        if row is None:
            return None
        return row_to_blackbox_run(dict(row))

    def list_by_task(self, task_id: str) -> list[BlackboxRun]:
        with self._pool.ro_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM blackbox_runs WHERE task_id = ? ORDER BY started_at DESC",
                (task_id,),
            ).fetchall()
        return [row_to_blackbox_run(dict(r)) for r in rows]

    def update_status(
        self,
        blackbox_run_id: str,
        status: str,
        completed_at: str | None = None,
    ) -> None:
        sets = ["status = ?"]
        values: list[Any] = [status]
        if completed_at is not None:
            sets.append("completed_at = ?")
            values.append(completed_at)
        values.append(blackbox_run_id)
        with self._pool.tx() as conn:
            conn.execute(
                f"UPDATE blackbox_runs SET {', '.join(sets)} WHERE blackbox_run_id = ?",
                values,
            )

    # ── CaptureQuality ──────────────────────────────────────

    def upsert_capture_quality(self, quality: CaptureQuality) -> None:
        with self._pool.tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO http_capture_quality (
                    blackbox_run_id, total_observed, accepted_started, persisted_count,
                    filtered_by_resource_type, filtered_cross_origin, filtered_by_method,
                    filtered_websocket_count, filtered_path_too_long,
                    dropped_pending_limit, dropped_run_limit, dropped_writer_queue_limit,
                    writer_retry_count, writer_failed_batch_count, persistence_failed,
                    truncated, truncation_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    quality.blackbox_run_id,
                    quality.total_observed,
                    quality.accepted_started,
                    quality.persisted_count,
                    quality.filtered_by_resource_type,
                    quality.filtered_cross_origin,
                    quality.filtered_by_method,
                    quality.filtered_websocket_count,
                    quality.filtered_path_too_long,
                    quality.dropped_pending_limit,
                    quality.dropped_run_limit,
                    quality.dropped_writer_queue_limit,
                    quality.writer_retry_count,
                    quality.writer_failed_batch_count,
                    quality.persistence_failed,
                    int(quality.truncated),
                    quality.truncation_reason,
                    quality.updated_at or _utc_now_iso(),
                ),
            )

    def get_capture_quality(self, blackbox_run_id: str) -> dict[str, Any] | None:
        """读取采集质量快照（供 storage 层复用，避免跨层访问 _pool）。"""
        with self._pool.ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM http_capture_quality WHERE blackbox_run_id = ?",
                (blackbox_run_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)
