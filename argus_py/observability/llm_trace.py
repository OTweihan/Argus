"""LLM 调用追踪记录。"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from argus_py.core.ids import generate_id
from argus_py.core.paths import OUTPUT_DIR
from argus_py.observability.context import current_context

logger = logging.getLogger(__name__)

# ── 事件类型 ──────────────────────────────────────────────
EVENT_LLM_STARTED = "task.llm.started"
EVENT_LLM_SUCCEEDED = "task.llm.succeeded"
EVENT_LLM_FAILED = "task.llm.failed"
EVENT_LLM_PARSE_FAILED = "task.llm.parse_failed"

# ── 配置（合并 server.yaml + 环境变量覆盖） ──────────────
_LLM_TRACE_ENABLED: bool | None = None  # None = 启动时从 ServerSettings 解析
_LLM_TRACE_MAX_SIZE_BYTES: int | None = None
_LLM_TRACE_CONTENT_REDACT: bool | None = None

_INITIALIZED = False


def _ensure_config() -> None:
    """懒加载配置：优先 server.yaml，环境变量覆盖。"""
    global _LLM_TRACE_ENABLED, _LLM_TRACE_MAX_SIZE_BYTES, _LLM_TRACE_CONTENT_REDACT, _INITIALIZED
    if _INITIALIZED:
        return

    from argus_py.config.server_settings import load_server_settings

    settings = load_server_settings()
    _LLM_TRACE_ENABLED = settings.llm_trace_enabled
    _LLM_TRACE_MAX_SIZE_BYTES = settings.llm_trace_max_size_mb * 1024 * 1024
    _LLM_TRACE_CONTENT_REDACT = settings.llm_trace_content_redact

    env_val = os.getenv("LLM_TRACE_ENABLED")
    if env_val is not None:
        _LLM_TRACE_ENABLED = env_val.strip().lower() in {"1", "true", "yes", "y", "on"}
    env_val = os.getenv("LLM_TRACE_MAX_SIZE_MB")
    if env_val is not None:
        try:
            _LLM_TRACE_MAX_SIZE_BYTES = int(env_val) * 1024 * 1024
        except ValueError:
            logger.warning("LLM_TRACE_MAX_SIZE_MB 不是有效整数：%r，使用 YAML 配置值", env_val)
    env_val = os.getenv("LLM_TRACE_CONTENT_REDACT")
    if env_val is not None:
        _LLM_TRACE_CONTENT_REDACT = env_val.strip().lower() in {"1", "true", "yes", "y", "on"}
    _INITIALIZED = True


# ── 脱敏配置 ──────────────────────────────────────────────
# 匹配到这些 key 时值被脱敏（精确匹配，不含子串）
_SENSITIVE_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "cookie", "password", "secret", "token"}
)
# 即使在敏感 dict 内也保留的诊断字段
_SAFELIST_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens", "token_usage"})

MASK = "***"

# ── 内容级脱敏 ────────────────────────────────────────────
# 内容级脱敏正则：匹配字符串值中的敏感模式
_CONTENT_REDACT_PATTERNS: list[re.Pattern[str]] = [
    # API Key: sk-... / sk-or-... (OpenAI 风格)
    re.compile(r"\b(sk-or-v1-[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"),
    # JWT: base64.base64.base64（跳过头尾伪码）
    re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"),
    # URL 内嵌凭据 ://user:pass@
    re.compile(r"(://)([^:/\s]+):([^@\s]+)@"),
    # 内联 key=value 或 key:value 形式的敏感字段
    re.compile(
        r'\b(api[_-]?key|apikey|password|secret|token)\s*[=:]\s*["\']?([^\s"\'&,;]+)["\']?',
        re.IGNORECASE,
    ),
]


def _redact_sensitive_content(text: str) -> str:
    """对字符串内容进行内容级脱敏，抹去内嵌的 API Key / JWT / 凭据等。"""
    result = text
    for pattern in _CONTENT_REDACT_PATTERNS:
        result = pattern.sub(lambda m: _content_replacement(m, pattern), result)
    return result


def _content_replacement(m: re.Match, pattern: re.Pattern[str]) -> str:
    # URL 内嵌凭据 → 保留协议和 host，遮掉密码部分
    if pattern == _CONTENT_REDACT_PATTERNS[3]:
        return m.group(1) + m.group(2) + ":***@"  # ://user:***@
    # key=value → key=***
    if pattern == _CONTENT_REDACT_PATTERNS[4]:
        return m.group(1) + "=" + MASK
    return MASK


def _redact_str_value(value: str) -> str:
    """对单个字符串值应用内容级脱敏。"""
    return _redact_sensitive_content(value)


def redact_trace_data(data: dict[str, Any]) -> dict[str, Any]:
    """递归脱敏敏感字段，支持 key 级和内容级脱敏。"""

    def _is_sensitive(key: str) -> bool:
        return key.strip().lower().replace("-", "_") in _SENSITIVE_KEYS

    def _is_safelisted(key: str) -> bool:
        return key.strip().lower().replace("-", "_") in _SAFELIST_KEYS

    def _recurse(value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for k, v in value.items():
                if _is_sensitive(k):
                    result[k] = MASK
                elif _is_safelisted(k):
                    result[k] = v
                else:
                    result[k] = _recurse(v)
            return result
        if isinstance(value, list):
            return [_recurse(item) for item in value]
        if isinstance(value, str):
            return _redact_str_value(value)
        return value

    return _recurse(data)


# 兼容旧导入路径的别名
_redact_trace_data = redact_trace_data


@dataclass
class LLMTraceRecord:
    """单次 LLM 调用的完整追踪记录。"""

    trace_id: str = ""
    task_id: str = ""
    phase: str = ""  # "planner" | "evaluator"
    event: str = ""

    # ── 调用方上下文 ──
    system_prompt: str = ""
    input_payload: dict[str, Any] = field(default_factory=dict)

    # ── 底层信息（由 LLMClient 填充） ──
    model: str = ""
    base_url_host: str = ""
    latency_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)

    # ── 响应与解析结果 ──
    raw_response: str = ""
    parsed_result: Any = None
    parse_error: str = ""

    # ── 错误信息 ──
    error: str = ""

    # ── 元信息 ──
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_trace_ctx(cls, ctx: dict[str, Any], event: str) -> "LLMTraceRecord":
        """从 trace_ctx 字典构建记录。task_id 优先取 ctx，否则从 current_context 自动读取。"""
        task_id = ctx.get("task_id") or current_context().get("task_id") or ""
        return cls(
            trace_id=ctx.get("trace_id", generate_id("trc")),
            task_id=task_id,
            phase=ctx.get("phase", ""),
            event=event,
            system_prompt=ctx.get("system_prompt", ""),
            input_payload=ctx.get("input_payload", {}),
            model=ctx.get("model", ""),
            base_url_host=ctx.get("base_url_host", ""),
            latency_ms=ctx.get("latency_ms", 0.0),
            token_usage=ctx.get("token_usage", {}),
            raw_response=ctx.get("raw_response", ""),
            parsed_result=ctx.get("parsed_result"),
            parse_error=ctx.get("parse_error", ""),
            error=ctx.get("error", ""),
        )


def write_trace(record: LLMTraceRecord) -> None:
    """追加一条追踪记录到 outputs/traces/{task_id}.jsonl。

    task_id 为空时跳过写入，避免产生无归属的 .jsonl 文件。
    受 server.yaml observability.llm_trace 和环境变量 LLM_TRACE_ENABLED / LLM_TRACE_MAX_SIZE_MB 控制。
    """
    _ensure_config()

    if not _LLM_TRACE_ENABLED:
        logger.debug("LLM 追踪已关闭，跳过写入：trace_id=%s", record.trace_id)
        return
    if not record.task_id:
        logger.warning(
            "LLM 追踪记录缺少 task_id，已丢弃：phase=%s event=%s", record.phase, record.event
        )
        return
    traces_dir = OUTPUT_DIR / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    file_path = traces_dir / f"{record.task_id}.jsonl"

    # 大小上限检查
    if (
        _LLM_TRACE_MAX_SIZE_BYTES is not None
        and _LLM_TRACE_MAX_SIZE_BYTES > 0
        and file_path.exists()
        and file_path.stat().st_size >= _LLM_TRACE_MAX_SIZE_BYTES
    ):
        logger.warning(
            "LLM 追踪文件超出大小上限 (%d MB)，跳过写入：%s",
            _LLM_TRACE_MAX_SIZE_BYTES // (1024 * 1024),
            file_path,
        )
        return

    data = asdict(record)
    redacted = redact_trace_data(data) if _LLM_TRACE_CONTENT_REDACT else data

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(redacted, ensure_ascii=False, default=str) + "\n")
