"""SQLite 基础设施。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from argus_py.core.paths import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "argus.db"

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
  max_tokens INTEGER NOT NULL,
  temperature REAL NOT NULL,
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


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """创建 SQLite 连接并设置运行参数。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


_REQUIRED_TASK_COLUMNS: dict[str, str] = {
    "current_step": "INTEGER NOT NULL DEFAULT 0",
}


def _migrate_tasks_table(connection: sqlite3.Connection) -> None:
    """检查 tasks 表并补全缺失列（兼容旧库迁移）。"""
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    for col_name, col_def in _REQUIRED_TASK_COLUMNS.items():
        if col_name not in existing:
            connection.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")


def init_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库表结构。"""
    with closing(connect(db_path)) as connection:
        with connection:
            connection.executescript(PROJECTS_SCHEMA)
            connection.executescript(MODEL_CONFIGS_SCHEMA)
            connection.executescript(TASKS_SCHEMA)
            connection.executescript(TASK_LOGS_SCHEMA)
            connection.executescript(FINDINGS_SCHEMA)
            _migrate_tasks_table(connection)
