"""系统配置加载。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from argus_py.core.paths import OUTPUT_DIR, resolve_project_path
from argus_py.core.constants import (
    DEFAULT_BROWSER,
    DEFAULT_HEADLESS,
    DEFAULT_MAX_STEPS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TASK_TIMEOUT_S,
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    """Argus 系统运行配置，不包含 LLM 密钥和模型配置。"""

    browser_headless: bool = DEFAULT_HEADLESS
    browser_type: str = DEFAULT_BROWSER
    max_steps: int = DEFAULT_MAX_STEPS
    task_timeout_s: int = DEFAULT_TASK_TIMEOUT_S
    output_dir: Path = OUTPUT_DIR

    @property
    def logs_dir(self) -> Path:
        return self.output_dir / "logs"

    @property
    def screenshots_dir(self) -> Path:
        return self.output_dir / "screenshots"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def temp_dir(self) -> Path:
        return self.output_dir / "temp"

    def ensure_output_dirs(self) -> None:
        """确保运行产物目录存在。"""
        for path in (self.logs_dir, self.screenshots_dir, self.reports_dir, self.temp_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_settings(env_file: str | Path = ".env") -> Settings:
    """从系统 .env 和环境变量加载配置。"""
    env_path = resolve_project_path(env_file)
    if env_path.exists():
        load_dotenv(env_path)

    return Settings(
        browser_headless=_env_bool("BROWSER_HEADLESS", DEFAULT_HEADLESS),
        browser_type=os.getenv("BROWSER_TYPE", DEFAULT_BROWSER),
        max_steps=_env_int("MAX_STEPS", DEFAULT_MAX_STEPS),
        task_timeout_s=_env_int("TASK_TIMEOUT_S", DEFAULT_TASK_TIMEOUT_S),
        output_dir=resolve_project_path(os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)),
    )
