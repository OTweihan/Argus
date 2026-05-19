"""SQLite 基础设施。"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from argus_py.core.paths import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "argus.db"

ConnectFn = Callable[[], sqlite3.Connection]
"""无参连接工厂签名（通常为 ``lambda: connect(db_path)``）。"""

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
  max_steps INTEGER NOT NULL DEFAULT 20,
  timeout_seconds INTEGER NOT NULL DEFAULT 300,
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
    "connect",
    "init_database",
    "_DefaultDBProbe",
]
