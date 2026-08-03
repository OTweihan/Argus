"""阶段四：CAS 并发认领 — 集成测试。

覆盖：双独立 SQLite 连接 + 同一 db 文件 → 同时 claim → 仅一个成功；
锁冲突不抛 exception 而返回 None；租约过期重试。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from argus_py.correlation.enums import (
    AttemptStatus,
)
from argus_py.correlation.models import CorrelationAttempt
from argus_py.task.storage import TaskSQLiteStorage

from tests.integration.correlation._fixtures import (
    setup_base_tables,
    setup_ready_correlation_run,
)


def _make_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _setup_base_data(db: Path) -> None:
    """初始化数据库并创建 READY 状态的 CorrelationRun。"""
    storage = setup_base_tables(db)
    setup_ready_correlation_run(storage)


def _run_claim(storage: TaskSQLiteStorage, cr_id: str, owner: str) -> CorrelationAttempt | None:
    """在一个连接中执行 claim，返回 attempt 或 None。"""
    return storage.claim_and_create_attempt(cr_id, owner)


def test_concurrent_claim_only_one_wins(tmp_path: Path) -> None:
    """两个独立连接同时 claim → 仅一个成功。"""
    db = tmp_path / "test.db"
    _setup_base_data(db)

    results: list[CorrelationAttempt | None] = [None, None]
    barrier = threading.Barrier(2, timeout=5)
    errors: list[Exception] = []

    def _claim_worker(idx: int) -> None:
        try:
            storage = TaskSQLiteStorage(db)
            barrier.wait()
            results[idx] = _run_claim(storage, "cr1", f"worker-{idx}")
        except Exception as exc:
            errors.append(exc)

    t0 = threading.Thread(target=_claim_worker, args=(0,))
    t1 = threading.Thread(target=_claim_worker, args=(1,))
    t0.start()
    t1.start()
    t0.join()
    t1.join()

    # 验收
    assert len(errors) == 0, f"Unexpected errors: {errors}"
    attempts = [r for r in results if r is not None]
    assert len(attempts) == 1, f"Expected exactly 1 winner, got {len(attempts)}"
    winner = attempts[0]
    assert winner.correlation_run_id == "cr1"
    assert winner.status == AttemptStatus.RUNNING
    assert winner.lease_owner == f"worker-{results.index(winner)}"

    # 数据库状态
    conn = _make_conn(db)
    try:
        running = conn.execute(
            """SELECT correlation_attempt_id, attempt_number, lease_owner
               FROM correlation_attempts
               WHERE correlation_run_id='cr1' AND status='RUNNING'"""
        ).fetchall()
        assert len(running) == 1, f"Expected 1 RUNNING attempt, got {len(running)}"
        assert running[0]["correlation_attempt_id"] == winner.correlation_attempt_id
        assert running[0]["attempt_number"] > 0
        assert running[0]["lease_owner"] == winner.lease_owner

        cr = conn.execute(
            "SELECT status FROM correlation_runs WHERE correlation_run_id='cr1'"
        ).fetchone()
        assert cr is not None
        assert cr["status"] == "RUNNING"
    finally:
        conn.close()


def test_concurrent_claim_no_database_locked_exception(tmp_path: Path) -> None:
    """失败方不抛 sqlite3.OperationalError: database is locked → 返回 None。"""
    db = tmp_path / "test.db"
    _setup_base_data(db)

    errors: list[Exception] = []

    def _worker(idx: int, barrier: threading.Barrier) -> CorrelationAttempt | None:
        try:
            storage = TaskSQLiteStorage(db)
            barrier.wait()
            return _run_claim(storage, "cr1", f"w-{idx}")
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                errors.append(e)
            return None

    barrier = threading.Barrier(2, timeout=5)
    t0 = threading.Thread(target=_worker, args=(0, barrier))
    t1 = threading.Thread(target=_worker, args=(1, barrier))
    t0.start()
    t1.start()
    t0.join()
    t1.join()

    assert len(errors) == 0, (
        f"Got database is locked errors: {errors}. "
        f"Repository should handle lock conflicts gracefully."
    )


def test_claim_with_expired_lease(tmp_path: Path) -> None:
    """租约过期后，新的 claim 可以成功。"""
    db = tmp_path / "test.db"
    _setup_base_data(db)

    # 首次 claim
    storage1 = TaskSQLiteStorage(db)
    attempt1 = storage1.claim_and_create_attempt("cr1", "w1")
    assert attempt1 is not None

    # 手动将 attempt 标记为 ABORTED（模拟过期）
    conn = _make_conn(db)
    try:
        conn.execute(
            "UPDATE correlation_attempts SET status='ABORTED' WHERE correlation_attempt_id=?",
            (attempt1.correlation_attempt_id,),
        )
        conn.execute(
            "UPDATE correlation_runs SET status='READY', active_attempt_id=NULL "
            "WHERE correlation_run_id='cr1'"
        )
        conn.commit()
    finally:
        conn.close()

    # 第二次 claim 应成功
    storage2 = TaskSQLiteStorage(db)
    attempt2 = storage2.claim_and_create_attempt("cr1", "w2")
    assert attempt2 is not None
    assert attempt2.attempt_number == 2
