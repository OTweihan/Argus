"""日志初始化。"""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import yaml

from argus_py.core.paths import LOGGING_CONFIG_FILE, resolve_project_path

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(config_path: str | Path = LOGGING_CONFIG_FILE) -> None:
    """从 YAML 初始化日志；配置不存在时使用基础配置。"""
    path = resolve_project_path(config_path)
    if not path.exists():
        logging.basicConfig(level=logging.INFO, format=DEFAULT_LOG_FORMAT)
        return

    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for handler in config.get("handlers", {}).values():
        filename = handler.get("filename")
        if filename:
            log_path = resolve_project_path(filename)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler["filename"] = str(log_path)
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """获取 Logger。已弃用，直接使用 ``logging.getLogger(__name__)`` 替代。"""
    import warnings

    warnings.warn(
        "get_logger 已弃用，请直接使用 logging.getLogger(__name__)",
        DeprecationWarning,
        stacklevel=2,
    )
    return logging.getLogger(name)
