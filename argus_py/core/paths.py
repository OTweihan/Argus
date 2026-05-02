"""项目路径解析。"""

from __future__ import annotations

import os
from pathlib import Path


def _find_project_root() -> Path:
    """定位项目根目录，支持用 ARGUS_PROJECT_ROOT 覆盖。"""
    override = os.getenv("ARGUS_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "argus_py").exists():
            return parent
    return current.parents[2]


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = _find_project_root()

CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = CONFIG_DIR / "prompts"
BROWSER_STATES_DIR = CONFIG_DIR / "browser-states"
BUILTIN_PROMPTS_DIR = PACKAGE_ROOT / "llm" / "prompts"
LOGGING_CONFIG_FILE = CONFIG_DIR / "logging.yaml"
LLM_ENV_FILE = CONFIG_DIR / "llm.env"

OUTPUT_DIR = PROJECT_ROOT / "outputs"
LOGS_DIR = OUTPUT_DIR / "logs"
SCREENSHOTS_DIR = OUTPUT_DIR / "screenshots"
REPORTS_DIR = OUTPUT_DIR / "reports"
TEMP_DIR = OUTPUT_DIR / "temp"
DATA_DIR = OUTPUT_DIR / "data"

REPORT_TEMPLATES_DIR = PACKAGE_ROOT / "report" / "templates"
API_STATIC_DIR = PACKAGE_ROOT / "api" / "static"


def resolve_project_path(path: str | Path) -> Path:
    """将相对路径解析到项目根目录下。"""
    value = Path(path).expanduser()
    if value.is_absolute():
        return value
    return PROJECT_ROOT / value
