"""DbPool 行为测试：并发取还、mode=ro 拒写、drain、pool_stats。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from argus_py.infra.db import DbPool


class TestDbPoolBasic:
    def test_acquire_release_rw(self, tmp_path: Path) -> None:
        pool = DbPool(tmp_path / "test.db")
        with pool.tx() as conn:
            conn.execute("CREATE TABLE t(x)")
            conn.execute("INSERT INTO t VALUES (1)")
        with pool.ro_conn() as conn:
            assert conn.execute("SELECT x FROM t").fetchone()["x"] == 1

    def test_acquire_release_ro(self, tmp_path: Path) -> None:
        pool = DbPool(tmp_path / "test_ro.db")
        with pool.tx() as conn:
            conn.execute("CREATE TABLE t(x)")
            conn.execute("INSERT INTO t VALUES (42)")
        with pool.ro_conn() as conn:
            row = conn.execute("SELECT x FROM t").fetchone()
            assert row is not None
            assert row["x"] == 42

    def test_ro_rejects_write(self, tmp_path: Path) -> None:
        """mode=ro 连接执行写入时应抛出 DatabaseError。"""
        pool = DbPool(tmp_path / "test_ro_write.db")
        with pool.tx() as conn:
            conn.execute("CREATE TABLE t(x)")
            conn.execute("INSERT INTO t VALUES (1)")
        with pool.ro_conn() as conn:
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute("INSERT INTO t VALUES (2)")

    def test_drain_closes_all_connections(self, tmp_path: Path) -> None:
        pool = DbPool(tmp_path / "test_drain.db", max_pool_size=4)
        conns = []
        for _ in range(4):
            c = pool._acquire(pool._rw_pool, "_rw_size", read_only=False)
            conns.append(c)
        for c in conns:
            pool._release(c, pool._rw_pool, "_rw_size")
        pool.drain()
        stats = pool.pool_stats()
        assert stats["rw_total"] == 0
        assert stats["ro_total"] == 0

    def test_pool_stats_accuracy(self, tmp_path: Path) -> None:
        pool = DbPool(tmp_path / "test_stats.db", max_pool_size=4)
        stats = pool.pool_stats()
        assert stats["rw_total"] == 0
        assert stats["ro_total"] == 0
        assert stats["max_size"] == 4
        c1 = pool._acquire(pool._rw_pool, "_rw_size", read_only=False)
        assert pool.pool_stats()["rw_total"] == 1
        assert pool.pool_stats()["rw_active"] == 1
        pool._release(c1, pool._rw_pool, "_rw_size")
        assert pool.pool_stats()["rw_total"] == 1
        assert pool.pool_stats()["rw_active"] == 0
        assert pool.pool_stats()["max_size"] == 4

    def test_drain_closes_borrowed_connection_when_returned(self, tmp_path: Path) -> None:
        pool = DbPool(tmp_path / "test_drain_borrowed.db", max_pool_size=1)
        connection = pool._acquire(pool._rw_pool, "_rw_size", read_only=False)
        pool.drain()
        assert pool.pool_stats()["rw_total"] == 1
        pool._release(connection, pool._rw_pool, "_rw_size")
        assert pool.pool_stats()["rw_total"] == 0
        with pytest.raises(RuntimeError, match="closed"):
            pool._acquire(pool._rw_pool, "_rw_size", read_only=False)

    def test_pool_max_size_respected(self, tmp_path: Path) -> None:
        """池满时 _acquire 不创建新连接，统计不超 max_size。"""
        pool = DbPool(tmp_path / "test_max.db", max_pool_size=2)
        conns = []
        for _ in range(2):
            c = pool._acquire(pool._rw_pool, "_rw_size", read_only=False)
            conns.append(c)
        # 池满，本次 acquire 应阻塞而非创建新连接
        # 用 timeout 线程模拟
        results: list[bool] = []

        def try_acquire() -> None:
            try:
                pool._acquire(pool._rw_pool, "_rw_size", read_only=False)
                results.append(True)
            except Exception:
                results.append(False)

        t = threading.Thread(target=try_acquire, daemon=True)
        t.start()
        t.join(timeout=0.5)
        # 池满时超出 max_size 不会创建新连接，而是 blocking get
        # pool_stats 反映当前状态
        assert pool.pool_stats()["rw_total"] == 2
        for c in conns:
            pool._release(c, pool._rw_pool, "_rw_size")


class TestDbPoolConcurrent:
    def test_concurrent_ro_reads(self, tmp_path: Path) -> None:
        """多个线程同时读 RO 连接不冲突。"""
        pool = DbPool(tmp_path / "test_concur_ro.db", max_pool_size=4)
        with pool.tx() as conn:
            conn.execute("CREATE TABLE t(x)")
            for i in range(100):
                conn.execute("INSERT INTO t VALUES (?)", (i,))

        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                with pool.ro_conn() as conn:
                    rows = conn.execute("SELECT COUNT(*) AS cnt FROM t").fetchone()
                    assert rows["cnt"] == 100
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=reader, daemon=True) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"并发 RO 读异常：{errors}"
