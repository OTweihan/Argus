"""SQLite 基础设施。"""

from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from argus_py.core.paths import DATA_DIR
from argus_py.infra.migrations import apply_migrations

DEFAULT_DB_PATH = DATA_DIR / "argus.db"

ConnectFn = Callable[[], sqlite3.Connection]
"""无参连接工厂签名（通常为 ``lambda: connect(db_path)``）。"""

# ── 进程级连接池 ───────────────────────────────────────────────────────────────

_DB_POOLS: dict[str, "DbPool"] = {}
"""按 db_path.resolve() 缓存的 DbPool 单例。"""
_DEFAULT_POOL_MAX_SIZE: int = 8
"""进程级默认连接池大小，可由 set_default_pool_max_size() 覆盖。"""
_DB_POOLS_LOCK = threading.Lock()


class DbPool:
    """线程安全的 SQLite 连接池。

    维护读写（RW）和只读（RO，``mode=ro`` URI）两个独立子池，防止只读查询
    意外触发写入（SQLite ``mode=ro`` 在文件层面拒绝写入）。

    使用方式
    --------
    ::

        pool = DbPool("/path/to/argus.db")

        # 只读查询
        with pool.ro_conn() as conn:
            row = conn.execute("SELECT ...").fetchone()

        # 写入（自动 commit / rollback）
        with pool.tx() as conn:
            conn.execute("INSERT ...", row)

        # 读写连接（非事务，极少使用）
        with pool.conn() as conn:
            ...
    """

    def __init__(self, db_path: str | Path, max_pool_size: int = 8) -> None:
        self._db_path = str(Path(db_path).resolve())
        self._max_size = max_pool_size
        # 读写连接池
        self._rw_pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_pool_size)
        self._rw_size = 0
        # 只读连接池（mode=ro URI）
        self._ro_pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_pool_size)
        self._ro_size = 0
        self._lock = threading.Lock()

    # ── 公共接口 ────────────────────────────────────────────────────────────

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        """获取读写连接，退出时归还池中。"""
        connection = self._acquire(self._rw_pool, "_rw_size", read_only=False)
        try:
            yield connection
        finally:
            self._release(connection, self._rw_pool, "_rw_size")

    @contextmanager
    def ro_conn(self) -> Iterator[sqlite3.Connection]:
        """获取只读连接（``mode=ro`` URI），退出时归还池中。

        SQLite ``mode=ro`` 在文件层面拒绝任何写入操作，为只读路径提供
        安全保障。
        """
        connection = self._acquire(self._ro_pool, "_ro_size", read_only=True)
        try:
            yield connection
        finally:
            self._release(connection, self._ro_pool, "_ro_size")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """获取连接并在事务上下文中执行，退出时归还池中。

        SQLite Connection 自身的上下文协议在 ``__exit__`` 时根据是否抛异常
        自动 ``commit`` / ``rollback``。
        """
        connection = self._acquire(self._rw_pool, "_rw_size", read_only=False)
        try:
            with connection:
                yield connection
        finally:
            self._release(connection, self._rw_pool, "_rw_size")

    def drain(self) -> None:
        """关闭池中所有连接，重置计数器。"""
        self._drain_pool(self._rw_pool)
        self._rw_size = 0
        self._drain_pool(self._ro_pool)
        self._ro_size = 0

    def pool_stats(self) -> dict[str, int]:
        """返回各池的活跃 / 最大连接数。"""
        return {
            "rw_active": self._max_size - self._rw_pool.qsize(),
            "rw_total": self._rw_size,
            "ro_active": self._max_size - self._ro_pool.qsize(),
            "ro_total": self._ro_size,
            "max_size": self._max_size,
        }

    # ── 内部 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _drain_pool(pool: queue.Queue[sqlite3.Connection]) -> None:
        while True:
            try:
                pool.get_nowait().close()
            except queue.Empty:
                break

    def _new_conn(self, read_only: bool) -> sqlite3.Connection:
        """创建新连接并设置运行时参数。

        ``check_same_thread=False`` 是连接池所必需：连接创建后被放入
        ``queue.Queue``，可能在任何工作线程中被取出使用。池通过队列保证
        同一时刻最多只有一个线程持有该连接，因此跨线程访问是安全的。
        """
        if read_only:
            connection = sqlite3.connect(
                f"file:{self._db_path}?mode=ro",
                timeout=5,
                check_same_thread=False,
                uri=True,
            )
        else:
            connection = sqlite3.connect(self._db_path, timeout=5, check_same_thread=False)
            connection.execute("PRAGMA journal_mode = WAL")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _acquire(
        self,
        pool: queue.Queue[sqlite3.Connection],
        size_attr: str,
        read_only: bool,
    ) -> sqlite3.Connection:
        """从池中取连接，池空且未达上限时创建新连接。"""
        try:
            return pool.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            current_size = getattr(self, size_attr)
            if current_size < self._max_size:
                setattr(self, size_attr, current_size + 1)
                return self._new_conn(read_only)
        # 所有连接都被借出 — 阻塞等待归还
        return pool.get()

    @staticmethod
    def _release(
        connection: sqlite3.Connection,
        pool: queue.Queue[sqlite3.Connection],
        size_attr: str,
    ) -> None:
        """归还连接至池；池满则关闭。"""
        try:
            pool.put_nowait(connection)
        except queue.Full:
            connection.close()


def set_default_pool_max_size(size: int) -> None:
    """设置进程级默认连接池大小。

    在首次调用 ``get_db_pool`` 前调用此函数可定制所有 DbPool 的默认大小。
    """
    global _DEFAULT_POOL_MAX_SIZE
    _DEFAULT_POOL_MAX_SIZE = size


def get_db_pool(db_path: str | Path = DEFAULT_DB_PATH, max_pool_size: int | None = None) -> DbPool:
    """获取（或创建）指定数据库文件的进程级 DbPool 单例。

    按 ``db_path.resolve()`` 缓存，相同路径返回同一池。
    ``max_pool_size`` 仅在首次创建时生效；``None`` 表示使用进程级默认值。
    """
    if max_pool_size is None:
        max_pool_size = _DEFAULT_POOL_MAX_SIZE
    resolved = str(Path(db_path).resolve())
    global _DB_POOLS
    if resolved not in _DB_POOLS:
        with _DB_POOLS_LOCK:
            if resolved not in _DB_POOLS:  # double-check
                _DB_POOLS[resolved] = DbPool(resolved, max_pool_size)
    return _DB_POOLS[resolved]


_MIN_SQLITE_VERSION = (3, 35, 0)
"""ALTER TABLE DROP COLUMN 需要 SQLite 3.35.0+。"""


def _check_sqlite_version() -> None:
    version = sqlite3.sqlite_version_info
    if version < _MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite 版本过低：{sqlite3.sqlite_version}（需要 {'.'.join(map(str, _MIN_SQLITE_VERSION))}+）。"
            f"请升级系统 SQLite 或使用更高版本的 Python。"
        )


PROJECTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  base_url TEXT,
  git_url TEXT,
  auth_state_name TEXT,
  default_max_steps INTEGER,
  default_timeout_seconds INTEGER,
  default_capture_screenshots INTEGER NOT NULL DEFAULT 1,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at);
"""

MODEL_CONFIGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_configs (
  model_config_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key TEXT,
  base_url TEXT NOT NULL,
  completions_path TEXT NOT NULL DEFAULT '/chat/completions',
  max_retries INTEGER NOT NULL,
  timeout_seconds REAL NOT NULL,
  task_type TEXT,
  is_default INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_configs_provider ON model_configs(provider);
CREATE INDEX IF NOT EXISTS idx_model_configs_task_type ON model_configs(task_type);
CREATE INDEX IF NOT EXISTS idx_model_configs_is_default ON model_configs(is_default);
"""

TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  name TEXT,
  start_url TEXT,
  task_type TEXT NOT NULL,
  status TEXT NOT NULL,
  project_id TEXT,
  max_steps INTEGER NOT NULL DEFAULT 20,   -- 默认值同步 argus_py.core.constants.DEFAULT_MAX_STEPS
  timeout_seconds INTEGER NOT NULL DEFAULT 300,  -- 默认值同步 argus_py.core.constants.DEFAULT_TASK_TIMEOUT_S
  capture_screenshots INTEGER NOT NULL DEFAULT 1,
  current_step INTEGER NOT NULL DEFAULT 0,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  report_path TEXT,
  result_summary TEXT,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status_project ON tasks(status, project_id);
"""

TASK_LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_logs (
  task_log_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
  step_number INTEGER NOT NULL,
  action TEXT NOT NULL,
  result TEXT NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  url_before TEXT,
  url_after TEXT,
  screenshot_path TEXT,
  message TEXT,
  error TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON task_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_task_step ON task_logs(task_id, step_number);
"""

FINDINGS_SCHEMA = """
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

CREATE INDEX IF NOT EXISTS idx_findings_task_id ON findings(task_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
CREATE INDEX IF NOT EXISTS idx_findings_type ON findings(finding_type);
"""

TASK_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_events (
  event_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  phase TEXT NOT NULL,
  step_number INTEGER NOT NULL DEFAULT 0,
  summary TEXT NOT NULL DEFAULT '',
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id);
CREATE INDEX IF NOT EXISTS idx_task_events_task_created ON task_events(task_id, created_at);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """创建 SQLite 连接并设置连接级运行参数。

    journal_mode 是数据库级永久设置，由 init_database 统一处理，
    避免每次新建连接都执行一次 PRAGMA 写入而触发额外 IO。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def with_conn(connect_fn: ConnectFn) -> Iterator[sqlite3.Connection]:
    """打开连接并在退出时关闭，用于纯读路径。

    取代调用方反复编写的 ``with closing(connect_fn()) as connection:`` 模板：

        with with_conn(self._connect) as conn:
            row = conn.execute("SELECT ...").fetchone()
    """
    connection = connect_fn()
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def with_tx(connect_fn: ConnectFn) -> Iterator[sqlite3.Connection]:
    """打开连接并在 ``with conn:`` 事务上下文里执行，退出时关闭连接。

    SQLite Connection 自身的上下文协议在 ``__exit__`` 时根据是否抛异常自动
    ``commit`` / ``rollback``；本 helper 在外层再加 try/finally 保证连接关闭。
    用于一次或多次写操作：

        with with_tx(self._connect) as conn:
            conn.execute("INSERT ...", row)
            conn.execute("UPDATE ...", row)
    """
    connection = connect_fn()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


_REQUIRED_TASK_COLUMNS: dict[str, str] = {
    "current_step": "INTEGER NOT NULL DEFAULT 0",
    "name": "TEXT",
}


def _migrate_tasks_table(connection: sqlite3.Connection) -> None:
    """检查 tasks 表并补全缺失列（兼容旧库迁移）。"""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}
    for col_name, col_def in _REQUIRED_TASK_COLUMNS.items():
        if col_name not in existing:
            connection.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")


_OBSOLETE_MODEL_CONFIG_COLUMNS = {"max_tokens", "temperature"}


def _migrate_model_configs_table(connection: sqlite3.Connection) -> None:
    """删除旧版 model_configs 表中已废弃的列（兼容旧库迁移）。"""
    existing = {
        row["name"] for row in connection.execute("PRAGMA table_info(model_configs)").fetchall()
    }
    for col in _OBSOLETE_MODEL_CONFIG_COLUMNS:
        if col in existing:
            connection.execute(f"ALTER TABLE model_configs DROP COLUMN {col}")


def init_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库表结构。

    WAL 是数据库级永久设置，在此处一次性切换；后续 connect() 不再每次写 PRAGMA。

    流程：
    1. baseline schema 用 ``CREATE TABLE IF NOT EXISTS`` 建好（首次部署 +
       历史升级用户都安全）。
    2. ``_migrate_tasks_table`` / ``_migrate_model_configs_table`` 是历史用户
       的就地 ALTER 兜底；保留但不再扩展。
    3. ``apply_migrations`` 应用 ``infra/migrations/sql/`` 下的版本化迁移。
       首次见到 ``schema_migrations`` 表时自动标 baseline=applied。
    """
    _check_sqlite_version()
    with closing(connect(db_path)) as connection:
        # journal_mode 是 SQLite 数据库级别的持久属性，设置一次即可永久生效
        connection.execute("PRAGMA journal_mode = WAL")
        with connection:
            connection.executescript(PROJECTS_SCHEMA)
            connection.executescript(MODEL_CONFIGS_SCHEMA)
            connection.executescript(TASKS_SCHEMA)
            connection.executescript(TASK_LOGS_SCHEMA)
            connection.executescript(FINDINGS_SCHEMA)
            connection.executescript(TASK_EVENTS_SCHEMA)
            _migrate_tasks_table(connection)
            _migrate_model_configs_table(connection)
        apply_migrations(connection)


class _DefaultDBProbe:
    """``argus_py.core.crypto.DBProbe`` 默认实现，通过 ``connect`` 查询数据库。

    该实现位于 ``infra`` 层，由 ``api/app.py`` 等上层创建并注入到
    ``ensure_fernet_key()``，避免 ``core/crypto.py`` 直接依赖 ``infra`` 层。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = db_path

    def has_encrypted_api_keys(self) -> bool:
        from contextlib import closing

        try:
            with closing(connect(self._db_path)) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM model_configs WHERE api_key LIKE 'f:%'"
                ).fetchone()
                return row is not None and row["cnt"] > 0
        except Exception:
            return False


__all__ = [
    "DEFAULT_DB_PATH",
    "ConnectFn",
    "DbPool",
    "connect",
    "get_db_pool",
    "set_default_pool_max_size",
    "init_database",
    "_DefaultDBProbe",
]
