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


def init_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库表结构。"""
    with closing(connect(db_path)) as connection:
        with connection:
            connection.executescript(PROJECTS_SCHEMA)
            connection.executescript(MODEL_CONFIGS_SCHEMA)
