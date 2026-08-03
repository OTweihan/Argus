"""阶段四：关联系统集成测试 — 共享 fixture。

提供各测试文件复用的数据库准备函数，避免 INSERT 模板重复。
"""

from __future__ import annotations

from pathlib import Path

from argus_py.infra.db import init_database
from argus_py.task.storage import TaskSQLiteStorage


def setup_base_tables(db: Path) -> TaskSQLiteStorage:
    """初始化数据库并插入 base 表数据（projects + tasks + blackbox_runs）。

    返回 TaskSQLiteStorage（已建表但未插入 correlation 数据）。
    """
    init_database(db)
    storage = TaskSQLiteStorage(db)
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO projects (project_id, name, created_at, updated_at) "
            "VALUES ('p1', 'test', '2024-01-01', '2024-01-01')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, goal, project_id, task_type, status, created_at) "
            "VALUES ('t1', 'test', 'p1', 'BLACKBOX', 'PENDING', '2024-01-01')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO blackbox_runs (blackbox_run_id, task_id, attempt, status, started_at) "
            "VALUES ('bb1', 't1', 1, 'PENDING', '2024-01-01')"
        )
    return storage


def setup_request_evidence(
    storage: TaskSQLiteStorage,
    request_evidence_id: str = "req1",
    blackbox_run_id: str = "bb1",
    task_id: str = "t1",
) -> None:
    """插入一条最小请求证据（供 FK 引用）。"""
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO http_request_evidence "
            "(request_evidence_id, blackbox_run_id, task_id, step_execution_id, request_sequence, "
            "http_method, normalized_path, display_path, origin, "
            "endpoint_match_eligibility, outcome, request_owner, captured_at) "
            "VALUES (?, ?, ?, NULL, 1, "
            "'GET', '/api/users', '/api/users', 'https://example.com', "
            "'CONFIRMED_ELIGIBLE', 'COMPLETED', 'FRAME', '2024-01-01')",
            (request_evidence_id, blackbox_run_id, task_id),
        )


def setup_ready_correlation_run(
    storage: TaskSQLiteStorage,
    correlation_run_id: str = "cr1",
    blackbox_run_id: str = "bb1",
    desired_snapshot_id: str = "abc123",
    config_digest: str = "d1",
    analysis_id: str = "analysis-1",
    snapshot_id: str = "abc123",
    projection_version: int = 1,
) -> None:
    """创建 READY 状态的 CorrelationRun。"""
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO correlation_runs (
                correlation_run_id, project_id, blackbox_run_id,
                desired_source_snapshot_id, correlation_config_digest,
                matcher_version, normalization_version,
                analysis_id, bound_source_snapshot_id, analysis_projection_version,
                status, created_at
            ) VALUES (
                ?, 'p1', ?, ?, ?, 'v1', 'v1', ?, ?, ?,
                'READY', '2024-01-01'
            )""",
            (
                correlation_run_id,
                blackbox_run_id,
                desired_snapshot_id,
                config_digest,
                analysis_id,
                snapshot_id,
                projection_version,
            ),
        )


def setup_running_correlation_run(
    storage: TaskSQLiteStorage,
    correlation_run_id: str = "cr1",
    blackbox_run_id: str = "bb1",
    analysis_id: str = "analysis-1",
    snapshot_id: str = "abc123",
    projection_version: int = 1,
) -> None:
    """创建 RUNNING 状态的 CorrelationRun。"""
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO correlation_runs (
                correlation_run_id, project_id, blackbox_run_id,
                desired_source_snapshot_id, correlation_config_digest,
                matcher_version, normalization_version,
                analysis_id, bound_source_snapshot_id, analysis_projection_version,
                status, created_at
            ) VALUES (
                ?, 'p1', ?, 'abc123', 'd1', 'v1', 'v1', ?, ?, ?,
                'RUNNING', '2024-01-01'
            )""",
            (
                correlation_run_id,
                blackbox_run_id,
                analysis_id,
                snapshot_id,
                projection_version,
            ),
        )


def setup_stale_attempt(
    storage: TaskSQLiteStorage,
    correlation_run_id: str,
    attempt_id: str,
    attempt_number: int = 1,
    lease_owner: str = "old-worker",
    lease_expires_at: str = "2024-01-01T00:00:01",
    status: str = "RUNNING",
) -> None:
    """插入一个 Attempt 并设置 active_attempt_id。"""
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO correlation_attempts (
                correlation_attempt_id, correlation_run_id, attempt_number,
                analysis_id, source_snapshot_id, analysis_projection_version,
                matcher_version, normalization_version, correlation_config_digest,
                status, evidence_completeness,
                lease_owner, heartbeat_at, lease_expires_at,
                started_at, created_at
            ) VALUES (
                ?, ?, ?,
                'analysis-1', 'abc123', 1,
                'v1', 'v1', 'd1',
                ?, 'COMPLETE',
                ?, '2024-01-01T00:00:00', ?,
                '2024-01-01', '2024-01-01'
            )""",
            (attempt_id, correlation_run_id, attempt_number, status, lease_owner, lease_expires_at),
        )
        conn.execute(
            "UPDATE correlation_runs SET active_attempt_id = ? WHERE correlation_run_id = ?",
            (attempt_id, correlation_run_id),
        )
