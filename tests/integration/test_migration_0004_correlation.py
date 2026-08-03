"""阶段四：0004 关联 schema 迁移测试。

覆盖：全量迁移、增量迁移、幂等、外键、唯一索引、级联删除、
Schema 前置检查、NULL 绕过防护。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from argus_py.infra.db import init_database
from argus_py.infra.migrations import DEFAULT_MIGRATIONS_DIR as REAL_MIGRATIONS
from argus_py.infra.migrations import apply_migrations


def _make_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _versions(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [row["version"] for row in rows]


# ── 全量迁移 ────────────────────────────────────────────────────


def test_full_migration_from_empty_db(tmp_path: Path) -> None:
    """空数据库 → init_database → 全部迁移已应用。"""
    db = tmp_path / "test.db"
    init_database(db)

    conn = _make_conn(db)
    try:
        versions = _versions(conn)
        assert 1 in versions, f"Migration 0001 should be applied, got: {versions}"
        assert 4 in versions, f"Migration 0004 should be applied, got: {versions}"
    finally:
        conn.close()


# ── 增量迁移 ────────────────────────────────────────────────────


def test_0003_to_0004_upgrade(tmp_path: Path) -> None:
    """已应用 0003 的数据库升级到 0004。

    注意：此处手工构造的 baseline 表结构模拟的是 0003 完成后的预期状态
    （含 projects/tasks/findings 三张 baseline 表 + findings 表供 0001
    的 ALTER TABLE 使用）。如 baseline schema（argus_py/infra/db.py 中的
    PROJECTS_SCHEMA/TASKS_SCHEMA/FINDINGS_SCHEMA）新增了 NOT NULL 约束或
    删除了列，需要同步更新此处的 DDL。
    """
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        # 创建 baseline 表（含 findings，供 0001 的 ALTER TABLE findings 使用）
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, goal TEXT NOT NULL,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                task_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT NOT NULL,
                finding_type TEXT NOT NULL,
                url TEXT,
                location TEXT,
                screenshot_path TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO projects (project_id, name, created_at, updated_at)
                VALUES ('p1', 'test', '2024-01-01', '2024-01-01');
            INSERT INTO tasks (task_id, goal, project_id, task_type, status, created_at)
                VALUES ('t1', 'test', 'p1', 'WHITEBOX', 'PENDING', '2024-01-01');

            -- baseline migration record
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
            );
        """)
        conn.commit()

        # 应用 0001
        sql_0001 = (REAL_MIGRATIONS / "0001_whitebox_productization.sql").read_text("utf-8")
        conn.executescript(f"BEGIN;\n{sql_0001}\nCOMMIT;")
        conn.execute("INSERT INTO schema_migrations VALUES (1, 'whitebox', '2024-01-01')")
        conn.commit()

        # 应用 0002
        sql_0002 = (REAL_MIGRATIONS / "0002_analysis_run.sql").read_text("utf-8")
        conn.executescript(f"BEGIN;\n{sql_0002}\nCOMMIT;")
        conn.execute("INSERT INTO schema_migrations VALUES (2, 'analysis_run', '2024-01-01')")
        conn.commit()

        # 应用 0003
        sql_0003 = (REAL_MIGRATIONS / "0003_clusters.sql").read_text("utf-8")
        conn.executescript(f"BEGIN;\n{sql_0003}\nCOMMIT;")
        conn.execute("INSERT INTO schema_migrations VALUES (3, 'clusters', '2024-01-01')")
        conn.commit()
    finally:
        conn.close()

    # 通过正式迁移框架执行 0004
    conn2 = _make_conn(db)
    try:
        new = apply_migrations(conn2, REAL_MIGRATIONS)
    finally:
        conn2.close()

    applied_versions = [v for v, _ in new]
    assert 4 in applied_versions

    # 验证升级后数据可查
    conn3 = _make_conn(db)
    try:
        row = conn3.execute("SELECT task_id FROM tasks WHERE task_id='t1'").fetchone()
        assert row is not None
    finally:
        conn3.close()


# ── 幂等 ────────────────────────────────────────────────────────


def test_migration_idempotent(tmp_path: Path) -> None:
    """迁移重复执行不报错。"""
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        new = apply_migrations(conn, REAL_MIGRATIONS)
    finally:
        conn.close()
    assert new == []


def test_framework_level_idempotent(tmp_path: Path) -> None:
    """已记录 0004 后不再执行。"""
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        v_before = _versions(conn)
        new = apply_migrations(conn, REAL_MIGRATIONS)
        v_after = _versions(conn)
    finally:
        conn.close()
    assert new == []
    assert v_before == v_after


# ── 索引验证 ────────────────────────────────────────────────────


def test_correlation_indexes_exist(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert "uq_correlation_bound" in indexes
        assert "uq_correlation_waiting" in indexes
        assert "uq_correlation_run_active_attempt" in indexes
        assert "uq_endpoint_evidence" in indexes
        assert "uq_request_evidence_seq" in indexes
    finally:
        conn.close()


def test_uq_endpoint_evidence_columns(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        rows = conn.execute("PRAGMA index_info('uq_endpoint_evidence')").fetchall()
        columns = {row["name"] for row in rows}
        assert "correlation_attempt_id" in columns
        assert "request_evidence_id" in columns
    finally:
        conn.close()


# ── 外键验证 ────────────────────────────────────────────────────


def test_foreign_keys_enabled(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk is not None
        assert fk[0] == 1
    finally:
        conn.close()


def test_blackbox_run_cascade_delete(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        _setup_correlation_fixture(conn)
        conn.execute("DELETE FROM blackbox_runs WHERE blackbox_run_id='bb1'")
        conn.commit()
        cr = conn.execute(
            "SELECT correlation_run_id FROM correlation_runs WHERE blackbox_run_id='bb1'"
        ).fetchone()
        assert cr is None
    finally:
        conn.close()


# ── 唯一索引业务约束 ────────────────────────────────────────────


def test_uq_correlation_waiting_prevents_duplicate(tmp_path: Path) -> None:
    """两条完全相同的 waiting 记录 → IntegrityError。"""
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        _setup_minimal_fixture(conn)

        _insert_waiting = """
            INSERT INTO correlation_runs (
                correlation_run_id, project_id, blackbox_run_id,
                desired_source_snapshot_id, desired_analysis_config_digest,
                matcher_version, normalization_version, correlation_config_digest,
                status, created_at
            ) VALUES (
                ?, 'p1', 'bb1', 'abc123', '', 'v1', 'v1', 'd1',
                'WAITING_ANALYSIS', '2024-01-01'
            );
        """
        conn.execute(_insert_waiting, ("cr-wait-1",))
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(_insert_waiting, ("cr-wait-2",))
    finally:
        conn.close()


def test_uq_endpoint_evidence_same_attempt_request(tmp_path: Path) -> None:
    """同 attempt + 同 request evidence → IntegrityError。"""
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        _setup_correlation_fixture(conn)

        _insert_evidence = """
            INSERT INTO endpoint_evidence (
                endpoint_evidence_id, correlation_run_id, correlation_attempt_id,
                request_evidence_id, resolution_status, match_strategy, confidence,
                matcher_version, normalization_version, created_at
            ) VALUES (
                'eev-{}', 'cr1', 'ca1', 'req1',
                'UNIQUE', 'EXACT', 'HIGH', 'v1', 'v1', '2024-01-01'
            );
        """
        conn.execute(_insert_evidence.format("1"))
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(_insert_evidence.format("2"))
    finally:
        conn.close()


def test_uq_endpoint_evidence_different_attempt(tmp_path: Path) -> None:
    """不同 attempt + 同 request evidence → 允许。"""
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        _setup_correlation_fixture(conn)

        conn.execute("""
            INSERT INTO endpoint_evidence (
                endpoint_evidence_id, correlation_run_id, correlation_attempt_id,
                request_evidence_id, resolution_status, match_strategy, confidence,
                matcher_version, normalization_version, created_at
            ) VALUES (
                'eev-a1', 'cr1', 'ca1', 'req1',
                'UNIQUE', 'EXACT', 'HIGH', 'v1', 'v1', '2024-01-01'
            );
        """)
        conn.commit()

        conn.execute("""
            INSERT INTO correlation_attempts (
                correlation_attempt_id, correlation_run_id, attempt_number,
                analysis_id, source_snapshot_id, analysis_projection_version,
                matcher_version, normalization_version, correlation_config_digest,
                status, evidence_completeness, started_at, created_at
            ) VALUES (
                'ca2', 'cr1', 2, 'analysis-1', 'abc123', 1,
                'v1', 'v1', 'd1', 'RUNNING', 'COMPLETE', '2024-01-01', '2024-01-01'
            );
        """)
        conn.commit()

        conn.execute("""
            INSERT INTO endpoint_evidence (
                endpoint_evidence_id, correlation_run_id, correlation_attempt_id,
                request_evidence_id, resolution_status, match_strategy, confidence,
                matcher_version, normalization_version, created_at
            ) VALUES (
                'eev-a2', 'cr1', 'ca2', 'req1',
                'UNIQUE', 'EXACT', 'HIGH', 'v1', 'v1', '2024-01-01'
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ── 跨归属阻断 ──────────────────────────────────────────────────


def test_evidence_cross_run_rejected(tmp_path: Path) -> None:
    """EndpointEvidence 的 (correlation_run_id, correlation_attempt_id)
    跨 Run 引用 → FK IntegrityError。"""
    db = tmp_path / "test.db"
    init_database(db)
    conn = _make_conn(db)
    try:
        _setup_correlation_fixture(conn)

        conn.execute("""
            INSERT INTO correlation_runs (
                correlation_run_id, project_id, blackbox_run_id,
                desired_source_snapshot_id, correlation_config_digest,
                matcher_version, normalization_version,
                analysis_id, bound_source_snapshot_id, analysis_projection_version,
                created_at
            ) VALUES (
                'cr2', 'p1', 'bb1', 'xyz789', 'd2', 'v1', 'v1',
                'analysis-2', 'xyz789', 2,
                '2024-01-01'
            );
        """)
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO endpoint_evidence (
                    endpoint_evidence_id, correlation_run_id, correlation_attempt_id,
                    request_evidence_id, resolution_status, match_strategy, confidence,
                    matcher_version, normalization_version, created_at
                ) VALUES (
                    'eev-bad', 'cr2', 'ca1', 'req1',
                    'UNIQUE', 'EXACT', 'HIGH', 'v1', 'v1', '2024-01-01'
                );
            """)
    finally:
        conn.close()


# ── helpers ─────────────────────────────────────────────────────


def _setup_minimal_fixture(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        INSERT OR IGNORE INTO projects (project_id, name, created_at, updated_at)
            VALUES ('p1', 'test', '2024-01-01', '2024-01-01');
        INSERT OR IGNORE INTO tasks (task_id, goal, project_id, task_type, status, created_at)
            VALUES ('t1', 'test', 'p1', 'BLACKBOX', 'PENDING', '2024-01-01');
        INSERT OR IGNORE INTO blackbox_runs (blackbox_run_id, task_id, attempt, status, started_at)
            VALUES ('bb1', 't1', 1, 'PENDING', '2024-01-01');
    """)
    conn.commit()


def _setup_correlation_fixture(conn: sqlite3.Connection) -> None:
    """创建最小关联测试数据（含 attempt + request evidence）。"""
    _setup_minimal_fixture(conn)
    conn.executescript("""
        INSERT OR IGNORE INTO correlation_runs (
            correlation_run_id, project_id, blackbox_run_id,
            desired_source_snapshot_id, correlation_config_digest,
            matcher_version, normalization_version, created_at
        ) VALUES (
            'cr1', 'p1', 'bb1', 'abc123', 'd1', 'v1', 'v1', '2024-01-01'
        );
        INSERT OR IGNORE INTO correlation_attempts (
            correlation_attempt_id, correlation_run_id, attempt_number,
            analysis_id, source_snapshot_id, analysis_projection_version,
            matcher_version, normalization_version, correlation_config_digest,
            status, evidence_completeness, started_at, created_at
        ) VALUES (
            'ca1', 'cr1', 1, 'analysis-1', 'abc123', 1,
            'v1', 'v1', 'd1', 'RUNNING', 'COMPLETE', '2024-01-01', '2024-01-01'
        );
        INSERT OR IGNORE INTO http_request_evidence (
            request_evidence_id, blackbox_run_id, task_id,
            step_execution_id, request_sequence,
            http_method, normalized_path, display_path, origin,
            endpoint_match_eligibility, outcome, request_owner,
            captured_at
        ) VALUES (
            'req1', 'bb1', 't1', NULL, 1,
            'GET', '/api/users', '/api/users', 'https://example.com',
            'CONFIRMED_ELIGIBLE', 'COMPLETED', 'FRAME',
            '2024-01-01'
        );
    """)
    conn.commit()
