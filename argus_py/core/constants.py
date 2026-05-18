"""应用级常量。"""

from __future__ import annotations

from pathlib import Path

from argus_py.core.paths import (
    LOGS_DIR,
    OUTPUT_DIR,
    REPORTS_DIR,
    SCREENSHOTS_DIR,
    TEMP_DIR,
)

PROJECT_NAME = "Argus"
PROJECT_TAGLINE = "Every bug has nowhere to hide."


def _resolve_version() -> str:
    """从已安装的包元数据读取版本，未安装时尝试解析 pyproject.toml。"""
    try:
        from importlib.metadata import version

        return version("argus")
    except Exception:
        pass
    # fallback：开发环境未安装时直接从 pyproject.toml 读取
    try:
        import tomllib

        pf = Path(__file__).resolve().parents[2] / "pyproject.toml"
        return tomllib.loads(pf.read_text(encoding="utf-8"))["project"]["version"]
    except Exception:
        return "0.0.0"


PROJECT_VERSION = _resolve_version()

DEFAULT_OUTPUT_DIR = str(OUTPUT_DIR)
DEFAULT_LOGS_DIR = str(LOGS_DIR)
DEFAULT_SCREENSHOTS_DIR = str(SCREENSHOTS_DIR)
DEFAULT_REPORTS_DIR = str(REPORTS_DIR)
DEFAULT_TEMP_DIR = str(TEMP_DIR)

DEFAULT_BROWSER = "chromium"
DEFAULT_HEADLESS = False
DEFAULT_ACTION_TIMEOUT_MS = 10000
DEFAULT_NAVIGATION_TIMEOUT_MS = 30000
DEFAULT_PAGE_READY_TIMEOUT_MS = 8000
DEFAULT_PAGE_SETTLE_MS = 500

DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_LLM_MODEL = "qwen3.5-plus"
DEFAULT_LLM_MAX_TOKENS = 4096
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_RETRIES = 5

DEFAULT_MAX_STEPS = 20
DEFAULT_TASK_TIMEOUT_S = 300

WS_KEEPALIVE_SECONDS = 30.0
