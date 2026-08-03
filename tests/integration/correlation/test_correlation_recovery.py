"""阶段四：进程恢复测试。

覆盖：RUNNING Attempt 租约过期 → ABORTED + Run 回退；
残留 SUCCEEDED Attempt 不自激活。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from argus_py.correlation.enums import (
    CorrelationRunStatus,
)
from argus_py.task.storage import TaskSQLiteStorage

from tests.integration.correlation._fixtures import (
    setup_base_tables,
    setup_running_correlation_run,
    setup_stale_attempt,
)


def _setup_running_with_expired_lease(db: Path) -> tuple[TaskSQLiteStorage, str, str]:
    """创建 RUNNING 状态 Run + lease 已过期的 Attempt。"""
    storage = setup_base_tables(db)
    setup_running_correlation_run(storage)
    setup_stale_attempt(storage, "cr1", "ca-stale")
    return storage, "cr1", "ca-stale"


def _setup_ready_with_succeeded_no_active(db: Path) -> tuple[TaskSQLiteStorage, str]:
    """创建 READY 状态 Run + SUCCEEDED Attempt 但没有 active_attempt_id。"""
    storage = setup_base_tables(db)
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO correlation_runs (
                correlation_run_id, project_id, blackbox_run_id,
                desired_source_snapshot_id, correlation_config_digest,
                matcher_version, normalization_version,
                analysis_id, bound_source_snapshot_id, analysis_projection_version,
                status, active_attempt_id, created_at
            ) VALUES (
                'cr1', 'p1', 'bb1', 'abc123', 'd1', 'v1', 'v1',
                'analysis-1', 'abc123', 1,
                'READY', NULL,
                '2024-01-01'
            )"""
        )
        conn.execute(
            """INSERT INTO correlation_attempts (
                correlation_attempt_id, correlation_run_id, attempt_number,
                analysis_id, source_snapshot_id, analysis_projection_version,
                matcher_version, normalization_version, correlation_config_digest,
                status, evidence_completeness,
                started_at, created_at
            ) VALUES (
                'ca-old', 'cr1', 1,
                'analysis-1', 'abc123', 1,
                'v1', 'v1', 'd1',
                'SUCCEEDED', 'COMPLETE',
                '2024-01-01', '2024-01-01'
            )"""
        )
    return storage, "cr1"


# ── 租约过期恢复 ──────────────────────────────────────────


def test_stale_attempt_aborted_and_run_reset(tmp_path: Path) -> None:
    """RUNNING Attempt + 租约过期 → ABORTED → Run→READY。"""
    db = tmp_path / "test.db"
    storage, cr_id, attempt_id = _setup_running_with_expired_lease(db)

    recovered = storage.recover_stale_attempts()
    assert len(recovered) >= 1
    recovered_ids = [a.correlation_attempt_id for a in recovered]
    assert attempt_id in recovered_ids

    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.status in (CorrelationRunStatus.READY, CorrelationRunStatus.FAILED), (
        f"Expected READY or FAILED, got {cr.status}"
    )

    # 验证旧 attempt 已 ABORTED
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT status FROM correlation_attempts WHERE correlation_attempt_id=?",
            (attempt_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "ABORTED"
    finally:
        conn.close()


def test_ready_with_unactivated_succeeded_not_auto_activate(tmp_path: Path) -> None:
    """READY 状态 + 残留 SUCCEEDED Attempt（无 active_attempt_id）→ 不自动激活。"""
    db = tmp_path / "test.db"
    storage, cr_id = _setup_ready_with_succeeded_no_active(db)

    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.status == CorrelationRunStatus.READY
    assert cr.active_attempt_id is None


def test_recover_then_reclaim(tmp_path: Path) -> None:
    """恢复后可以重新认领。"""
    db = tmp_path / "test.db"
    storage, cr_id, _ = _setup_running_with_expired_lease(db)

    storage.recover_stale_attempts()

    new_attempt = storage.claim_and_create_attempt(cr_id, "new-worker")
    assert new_attempt is not None
    assert new_attempt.attempt_number == 2
    assert new_attempt.lease_owner == "new-worker"
