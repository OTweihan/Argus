"""应用级常量与工具函数。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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

# DEFAULT_BROWSER / DEFAULT_HEADLESS 留在 core：除 browser 子树外，
# argus_py.config.settings 也读它们填充全局 Settings.
DEFAULT_BROWSER = "chromium"
DEFAULT_HEADLESS = False

DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_LLM_MODEL = "qwen3.5-plus"
DEFAULT_LLM_MAX_TOKENS = 4096
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_RETRIES = 5

DEFAULT_MAX_STEPS = 20
DEFAULT_TASK_TIMEOUT_S = 300

# Strategy inference thresholds — 按任务复杂度递进
DEFAULT_SIMPLE_TASK_STEPS = 6
DEFAULT_SIMPLE_TASK_TIMEOUT_S = 180
DEFAULT_NORMAL_TASK_STEPS = 12
DEFAULT_NORMAL_TASK_TIMEOUT_S = DEFAULT_TASK_TIMEOUT_S  # 300
DEFAULT_COMPLEX_TASK_STEPS = DEFAULT_MAX_STEPS  # 20
DEFAULT_COMPLEX_TASK_TIMEOUT_S = 600

# Task search — 最小搜索关键词长度，低于此值跳过 LIKE 匹配以避免全表扫描
TASK_SEARCH_MIN_LENGTH = 2
# 任务搜索涉及的字段列表（同时用于 Python 端内存搜索和 SQL LIKE 查询）
KEYWORD_FIELDS = ("name", "goal", "task_id", "start_url", "result_summary", "error_message")


def utc_now() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)
