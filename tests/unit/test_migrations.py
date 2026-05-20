"""验证 schema migration 框架：

- 首次启用：建表 + baseline 自动标记
- 文件迁移：按版本号顺序应用
- 重复运行：幂等
- 失败：回滚事务，schema_migrations 不留垃圾记录
- 版本号冲突 / 占用保留字段：拒绝
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from argus_py.infra.migrations import apply_migrations


def _make_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _versions(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [row["version"] for row in rows]


def test_empty_dir_creates_baseline(tmp_path: Path) -> None:
    """空迁移目录 → 只插入 baseline v0 记录。"""
    db = tmp_path / "test.db"
    migrations = tmp_path / "sql"
    migrations.mkdir()
    conn = _make_conn(db)
    try:
        new = apply_migrations(conn, migrations)
    finally:
        conn.close()

    assert new == []  # 没有新迁移
    conn = _make_conn(db)
    try:
        assert _versions(conn) == [0]
    finally:
        conn.close()


def test_missing_dir_is_ok(tmp_path: Path) -> None:
    """迁移目录不存在 → 仅初始化 schema_migrations 表，不报错。"""
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        new = apply_migrations(conn, tmp_path / "nonexistent")
    finally:
        conn.close()

    assert new == []
    conn = _make_conn(db)
    try:
        assert _versions(conn) == [0]
    finally:
        conn.close()


def test_applies_migrations_in_order(tmp_path: Path) -> None:
    """版本号顺序应用，乱序文件名也按 version 排。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "0002_add_b.sql").write_text(
        "CREATE TABLE b (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (migrations / "0001_add_a.sql").write_text(
        "CREATE TABLE a (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        new = apply_migrations(conn, migrations)
    finally:
        conn.close()

    assert new == [(1, "add_a"), (2, "add_b")]
    conn = _make_conn(db)
    try:
        assert _versions(conn) == [0, 1, 2]
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"a", "b"} <= tables
    finally:
        conn.close()


def test_idempotent_on_rerun(tmp_path: Path) -> None:
    """已应用版本不重复执行。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "0001_t.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    db = tmp_path / "test.db"

    conn = _make_conn(db)
    try:
        first = apply_migrations(conn, migrations)
    finally:
        conn.close()
    assert first == [(1, "t")]

    conn = _make_conn(db)
    try:
        second = apply_migrations(conn, migrations)
    finally:
        conn.close()
    assert second == []  # 第二次没有新应用


def test_failure_rolls_back(tmp_path: Path) -> None:
    """单文件失败 → 该迁移整体回滚，schema_migrations 不写入。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "0001_bad.sql").write_text(
        "CREATE TABLE good (id INTEGER); INVALID SQL HERE;",
        encoding="utf-8",
    )
    db = tmp_path / "test.db"

    conn = _make_conn(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(conn, migrations)
    finally:
        conn.close()

    conn = _make_conn(db)
    try:
        # baseline 已记录，但 v1 不应进入 schema_migrations
        assert _versions(conn) == [0]
        # good 表也不应该存在（事务回滚）
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='good'"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


def test_failure_stops_subsequent_migrations(tmp_path: Path) -> None:
    """前一个文件失败 → 后续文件不再执行（避免 schema 错位）。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "0001_bad.sql").write_text("INVALID;", encoding="utf-8")
    (migrations / "0002_should_skip.sql").write_text(
        "CREATE TABLE never_created (id INTEGER);", encoding="utf-8"
    )
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(conn, migrations)
    finally:
        conn.close()

    conn = _make_conn(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='never_created'"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


def test_version_zero_reserved(tmp_path: Path) -> None:
    """禁止 0000_xxx.sql：v0 是 baseline 保留位。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "0000_reserved.sql").write_text("SELECT 1;", encoding="utf-8")
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        with pytest.raises(RuntimeError, match="保留为 baseline"):
            apply_migrations(conn, migrations)
    finally:
        conn.close()


def test_duplicate_versions_rejected(tmp_path: Path) -> None:
    """两个文件用同一版本号 → 拒绝执行。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (migrations / "0001_b.sql").write_text("SELECT 1;", encoding="utf-8")
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        with pytest.raises(RuntimeError, match="重复版本号"):
            apply_migrations(conn, migrations)
    finally:
        conn.close()


def test_ignores_non_sql_files(tmp_path: Path) -> None:
    """README / .gitkeep 等非 NNNN_xxx.sql 文件应被跳过。"""
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "README.md").write_text("# docs", encoding="utf-8")
    (migrations / ".gitkeep").write_text("", encoding="utf-8")
    (migrations / "notes.txt").write_text("foo", encoding="utf-8")
    (migrations / "0001_real.sql").write_text(
        "CREATE TABLE real_table (id INTEGER);", encoding="utf-8"
    )
    db = tmp_path / "test.db"
    conn = _make_conn(db)
    try:
        new = apply_migrations(conn, migrations)
    finally:
        conn.close()
    assert new == [(1, "real")]


def test_init_database_includes_migrations(tmp_path: Path) -> None:
    """init_database 调用链应自动创建 schema_migrations 表 + baseline 记录。"""
    from argus_py.infra.db import init_database

    db = tmp_path / "argus.db"
    init_database(db)

    conn = _make_conn(db)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "schema_migrations" in tables
        assert _versions(conn) == [0]
    finally:
        conn.close()
