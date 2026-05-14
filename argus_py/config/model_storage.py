"""模型配置 SQLite 存储。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_py.config.models import ModelConfig
from argus_py.core.crypto import decrypt_api_key, encrypt_api_key
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import ModelConfigError
from argus_py.infra.db import DEFAULT_DB_PATH, connect, init_database, with_conn, with_tx


class ModelConfigSQLiteStorage:
    """基于 SQLite 的模型配置存储。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)
        # 复用同一个连接工厂，与 Repository 层风格统一。
        self._connect = lambda: connect(self.db_path)

    def save(self, config: ModelConfig) -> ModelConfig:
        """保存模型配置，存在时覆盖。"""
        with with_tx(self._connect) as conn:
            if config.is_default:
                self._clear_default(conn, config.task_type, exclude_id=config.model_config_id)
            conn.execute(
                """
                INSERT INTO model_configs (
                  model_config_id,
                  name,
                  provider,
                  model,
                  api_key,
                  base_url,
                  completions_path,
                  max_retries,
                  timeout_seconds,
                  task_type,
                  is_default,
                  enabled,
                  created_at,
                  updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_config_id) DO UPDATE SET
                  name = excluded.name,
                  provider = excluded.provider,
                  model = excluded.model,
                  api_key = excluded.api_key,
                  base_url = excluded.base_url,
                  completions_path = excluded.completions_path,
                  max_retries = excluded.max_retries,
                  timeout_seconds = excluded.timeout_seconds,
                  task_type = excluded.task_type,
                  is_default = excluded.is_default,
                  enabled = excluded.enabled,
                  updated_at = excluded.updated_at
                """,
                self._to_row(config),
            )
        return config

    def load(self, model_config_id: str) -> ModelConfig:
        """按 ID 读取模型配置。"""
        with with_conn(self._connect) as conn:
            row = conn.execute(
                "SELECT * FROM model_configs WHERE model_config_id = ?",
                (model_config_id,),
            ).fetchone()
        if row is None:
            raise ModelConfigError(f"Model config not found: {model_config_id}")
        return self._from_row(row)

    def list_configs(self, include_disabled: bool = True) -> list[ModelConfig]:
        """列出模型配置。"""
        sql = "SELECT * FROM model_configs"
        params: tuple[Any, ...] = ()
        if not include_disabled:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY is_default DESC, created_at DESC"
        with with_conn(self._connect) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, model_config_id: str) -> None:
        """删除模型配置。"""
        with with_tx(self._connect) as conn:
            cursor = conn.execute(
                "DELETE FROM model_configs WHERE model_config_id = ?",
                (model_config_id,),
            )
        if cursor.rowcount == 0:
            raise ModelConfigError(f"Model config not found: {model_config_id}")

    def find_default(self, task_type: TaskType | None = None) -> ModelConfig | None:
        """查找默认模型配置，优先匹配任务类型。"""
        with with_conn(self._connect) as conn:
            if task_type is not None:
                row = conn.execute(
                    """
                    SELECT * FROM model_configs
                    WHERE enabled = 1 AND is_default = 1 AND task_type = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (task_type.value,),
                ).fetchone()
                if row is not None:
                    return self._from_row(row)
            row = conn.execute(
                """
                SELECT * FROM model_configs
                WHERE enabled = 1 AND is_default = 1 AND task_type IS NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """,
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def _clear_default(
        self,
        connection: Any,
        task_type: TaskType | None,
        exclude_id: str,
    ) -> None:
        """清理同一作用域下的其它默认配置。"""
        if task_type is None:
            connection.execute(
                """
                UPDATE model_configs
                SET is_default = 0
                WHERE task_type IS NULL AND model_config_id <> ?
                """,
                (exclude_id,),
            )
            return
        connection.execute(
            """
            UPDATE model_configs
            SET is_default = 0
            WHERE task_type = ? AND model_config_id <> ?
            """,
            (task_type.value, exclude_id),
        )

    def _to_row(self, config: ModelConfig) -> tuple[Any, ...]:
        """将模型配置实体转换为 SQLite 参数。"""
        return (
            config.model_config_id,
            config.name,
            config.provider,
            config.model,
            encrypt_api_key(config.api_key),
            config.base_url,
            config.completions_path,
            config.max_retries,
            config.timeout_seconds,
            config.task_type.value if config.task_type else None,
            1 if config.is_default else 0,
            1 if config.enabled else 0,
            config.created_at.isoformat(),
            config.updated_at.isoformat(),
        )

    def _from_row(self, row: Any) -> ModelConfig:
        """将 SQLite 行转换为模型配置实体。"""
        return ModelConfig.from_dict(
            {
                "model_config_id": row["model_config_id"],
                "name": row["name"],
                "provider": row["provider"],
                "model": row["model"],
                "api_key": decrypt_api_key(row["api_key"]),
                "base_url": row["base_url"],
                "completions_path": row["completions_path"],
                "max_retries": row["max_retries"],
                "timeout_seconds": row["timeout_seconds"],
                "task_type": row["task_type"],
                "is_default": bool(row["is_default"]),
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
