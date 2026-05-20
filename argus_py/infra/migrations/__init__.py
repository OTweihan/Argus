"""SQLite schema 版本化迁移。

私网部署形态下每次升级版本都可能涉及 schema 变更，老靠 ``ALTER TABLE ADD
COLUMN`` 内联在 ``init_database`` 里堆叠不可持续：缺乏版本记录、无法回溯、
失败可能让数据库半天表状态。本模块提供基于文件版本号的顺序迁移机制：

- ``migrations/sql/{version:04d}_{description}.sql`` 按版本号排序
- ``schema_migrations`` 表记录已应用版本，避免重复执行
- 启动期 ``apply_migrations()`` 顺序应用未执行的迁移，每个文件单独事务保护

baseline 约定：
    - v0 = 现有 ``init_database()`` 用 ``CREATE TABLE IF NOT EXISTS`` 建立的所有表
    - 新装库：先建 baseline，再标 v0 applied，开始扫 v1+
    - 历史升级库：首次见到 ``schema_migrations`` 表不存在，自动标 v0 applied
      （baseline 已通过 IF NOT EXISTS 路径建好，不重复执行）

未来新增 schema 改动 → 添加 ``migrations/sql/000N_xxx.sql``，不要再在
``_migrate_tasks_table`` 这类内联函数里加新行。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATION_FILE_RE = re.compile(r"^(\d{4})_(.+)\.sql$")

_BASELINE_VERSION = 0
_BASELINE_NAME = "baseline_existing_schema"

DEFAULT_MIGRATIONS_DIR = Path(__file__).parent / "sql"


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    """schema_migrations 表自身用 IF NOT EXISTS 创建，避免无限递归。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
        """)


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    cursor = conn.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cursor.fetchall()}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_migrations(migrations_dir: Path) -> list[tuple[int, str, Path]]:
    """扫描迁移目录，返回 (version, name, path)，按 version 升序。

    忽略 ``.gitkeep`` / ``README.md`` 等非 SQL 文件；命名不符合 ``NNNN_xxx.sql``
    模式的文件也跳过（视为目录内的辅助资源）。
    """
    items: list[tuple[int, str, Path]] = []
    if not migrations_dir.exists():
        return items
    for entry in sorted(migrations_dir.iterdir()):
        if not entry.is_file():
            continue
        m = _MIGRATION_FILE_RE.match(entry.name)
        if not m:
            continue
        version = int(m.group(1))
        if version == _BASELINE_VERSION:
            raise RuntimeError(f"迁移版本 0 被保留为 baseline，请从 0001 开始：{entry}")
        name = m.group(2)
        items.append((version, name, entry))
    items.sort(key=lambda x: x[0])
    return items


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: Path | None = None,
) -> list[tuple[int, str]]:
    """按版本号顺序应用尚未执行的迁移，返回本次新应用的 (version, name) 列表。

    事务策略（绕开 SQLite ``executescript`` 的陷阱）：
        ``Connection.executescript()`` 会在开始时**隐式 COMMIT** 当前事务，
        意味着 ``with conn:`` 这种 Python 层事务上下文对 user SQL 无效。
        实际做法：把 user SQL 用 ``BEGIN; ...; COMMIT;`` 包成完整 script
        交给 ``executescript`` —— 失败时 SQLite 会自动回滚到 BEGIN，确保
        该迁移的所有改动是原子的；成功后再用独立 ``execute`` + ``commit``
        写 ``schema_migrations`` 一行。

        user SQL 成功但 INSERT schema_migrations 失败的极端窗口下，下次启动
        会再次执行 user SQL。所以迁移文件必须幂等（``CREATE TABLE IF NOT
        EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` 等），README 已要求。

    任一迁移失败抛出原异常并中断后续迁移（不静默跳过，让运维介入）。
    ``migrations_dir`` 默认为 ``argus_py/infra/migrations/sql``。
    """
    target_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    _ensure_migration_table(conn)
    conn.commit()
    applied = _applied_versions(conn)
    if _BASELINE_VERSION not in applied:
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (_BASELINE_VERSION, _BASELINE_NAME, _utc_now_iso()),
        )
        conn.commit()
        applied.add(_BASELINE_VERSION)

    discovered = _discover_migrations(target_dir)
    duplicates = _detect_duplicate_versions(discovered)
    if duplicates:
        raise RuntimeError(f"迁移目录存在重复版本号：{sorted(duplicates)}，请重命名后重试。")

    new_applied: list[tuple[int, str]] = []
    for version, name, path in discovered:
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        wrapped = f"BEGIN;\n{sql}\nCOMMIT;"
        try:
            conn.executescript(wrapped)
        except Exception:
            logger.exception("schema 迁移失败：version=%s name=%s file=%s", version, name, path)
            # 显式 rollback 抹掉可能还未 COMMIT 的部分写入（防御性）
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, _utc_now_iso()),
        )
        conn.commit()
        new_applied.append((version, name))
        logger.info("schema 迁移已应用：version=%s name=%s", version, name)
    return new_applied


def _detect_duplicate_versions(items: list[tuple[int, str, Path]]) -> set[int]:
    seen: set[int] = set()
    dup: set[int] = set()
    for version, _name, _path in items:
        if version in seen:
            dup.add(version)
        seen.add(version)
    return dup


__all__ = [
    "DEFAULT_MIGRATIONS_DIR",
    "apply_migrations",
]
