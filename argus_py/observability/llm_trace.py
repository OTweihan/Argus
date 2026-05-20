"""LLM 调用追踪记录。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from argus_py.core.ids import generate_id
from argus_py.core.paths import OUTPUT_DIR
from argus_py.observability.context import current_context
from argus_py.observability.redaction import _is_sensitive_key

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


def reset_config_for_tests() -> None:
    """测试钩子：强制下一次 ``write_trace`` 重新加载配置。

    生产代码不应调用；存在的目的是让单测在改环境变量后立即生效。
    """
    global _LLM_TRACE_ENABLED, _LLM_TRACE_MAX_SIZE_BYTES, _LLM_TRACE_CONTENT_REDACT, _INITIALIZED
    _LLM_TRACE_ENABLED = None
    _LLM_TRACE_MAX_SIZE_BYTES = None
    _LLM_TRACE_CONTENT_REDACT = None
    _INITIALIZED = False


# ── 脱敏配置 ──────────────────────────────────────────────
# 敏感 key 判断委托给 redaction._is_sensitive_key（子串匹配，与日志脱敏行为一致）
# 即使命中敏感 key 也保留的诊断字段（子串匹配下 total_tokens 会命中 token）
_SAFELIST_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens", "token_usage"})

MASK = "***"

# ── 内容级脱敏 ────────────────────────────────────────────
# 内容级脱敏正则：匹配字符串值中的敏感模式
# 用命名常量而非列表索引，避免顺序变化导致 _content_replacement 分支失效。
_PATTERN_SK_OR = re.compile(r"\b(sk-or-v1-[A-Za-z0-9]{20,})\b")
_PATTERN_SK = re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b")
_PATTERN_JWT = re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b")
_PATTERN_URL_CRED = re.compile(r"(://)([^:/\s]+):([^@\s]+)@")
_PATTERN_KV = re.compile(
    r'\b(api[_-]?key|apikey|password|secret|token)\s*[=:]\s*["\']?([^\s"\'&,;]+)["\']?',
    re.IGNORECASE,
)

_CONTENT_REDACT_PATTERNS: list[re.Pattern[str]] = [
    _PATTERN_SK_OR,
    _PATTERN_SK,
    _PATTERN_JWT,
    _PATTERN_URL_CRED,
    _PATTERN_KV,
]


def _redact_sensitive_content(text: str) -> str:
    """对字符串内容进行内容级脱敏，抹去内嵌的 API Key / JWT / 凭据等。"""
    result = text
    for pattern in _CONTENT_REDACT_PATTERNS:
        # 用默认参数把 pattern 立即绑死到 lambda 闭包，避免循环变量延迟绑定
        # （ruff B023）。本处 sub 是同步立即调用、不会真触发延迟问题，但显式
        # 绑定让规则不再误报，也对未来重构更友好。
        def replace_match(match: re.Match[str], bound_pattern: re.Pattern[str] = pattern) -> str:
            return _content_replacement(match, bound_pattern)

        result = pattern.sub(replace_match, result)
    return result


def _content_replacement(m: re.Match, pattern: re.Pattern[str]) -> str:
    # URL 内嵌凭据 → 保留协议和 host，遮掉密码部分
    if pattern is _PATTERN_URL_CRED:
        return m.group(1) + m.group(2) + ":***@"  # ://user:***@
    # key=value → key=***
    if pattern is _PATTERN_KV:
        return m.group(1) + "=" + MASK
    return MASK


def _redact_str_value(value: str) -> str:
    """对单个字符串值应用内容级脱敏。"""
    return _redact_sensitive_content(value)


def redact_trace_data(data: dict[str, Any]) -> dict[str, Any]:
    """递归脱敏敏感字段，支持 key 级和内容级脱敏。"""

    def _is_sensitive(key: str) -> bool:
        return _is_sensitive_key(key)

    def _is_safelisted(key: str) -> bool:
        return key.strip().lower().replace("-", "_") in _SAFELIST_KEYS

    def _recurse(value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for k, v in value.items():
                if _is_safelisted(k):
                    result[k] = v
                elif _is_sensitive(k):
                    result[k] = MASK
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


class LLMTraceRecord(BaseModel):
    """单次 LLM 调用的完整追踪记录。"""

    model_config = ConfigDict(populate_by_name=True)

    trace_id: str = Field(default="", alias="traceId")
    task_id: str = Field(default="", alias="taskId")
    phase: str = ""
    event: str = ""

    # ── 调用方上下文 ──
    system_prompt: str = Field(default="", alias="systemPrompt")
    input_payload: dict[str, Any] = Field(default_factory=dict, alias="inputPayload")

    # ── 底层信息（由 LLMClient 填充） ──
    model: str = ""
    base_url_host: str = Field(default="", alias="baseUrlHost")
    latency_ms: float = Field(default=0.0, alias="latencyMs")
    token_usage: dict[str, int] = Field(default_factory=dict, alias="tokenUsage")

    # ── 响应与解析结果 ──
    raw_response: str = Field(default="", alias="rawResponse")
    parsed_result: Any = Field(default=None, alias="parsedResult")
    parse_error: str = Field(default="", alias="parseError")

    # ── 错误信息 ──
    error: str = ""

    # ── 元信息 ──
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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


async def write_trace(record: LLMTraceRecord) -> None:
    """追加一条追踪记录到 outputs/traces/{task_id}.jsonl。

    task_id 为空时跳过写入，避免产生无归属的 .jsonl 文件。
    受 server.yaml observability.llm_trace 和环境变量 LLM_TRACE_ENABLED / LLM_TRACE_MAX_SIZE_MB 控制。

    写入路径优先走 ``LLMTraceWriter`` 后台批量写入（已启动时）；未启动或
    enqueue 失败时回退到 ``asyncio.to_thread`` 同步 append，保证 CLI / 测试场景兼容。
    model_dump / 脱敏 / 序列化均在后台线程执行，不阻塞事件循环。
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
    file_path = traces_dir / f"{record.task_id}.jsonl"

    # 走后台 writer，stat 与序列化在 writer 线程执行。
    from argus_py.observability.llm_trace_writer import get_trace_writer

    writer = get_trace_writer()
    if writer is not None and writer.enqueue(file_path, record):
        return

    # Fallback: 在 IO 线程中同步写入（CLI / 测试 / writer 队列满）。
    await asyncio.to_thread(_sync_write_trace, file_path, record)


def _sync_write_trace(file_path: Path, record: LLMTraceRecord) -> None:
    """在 IO 线程中同步写入单条 trace（fallback 路径）。"""
    _ensure_config()

    if (
        _LLM_TRACE_MAX_SIZE_BYTES is not None
        and _LLM_TRACE_MAX_SIZE_BYTES > 0
        and file_path.exists()
        and file_path.stat().st_size >= _LLM_TRACE_MAX_SIZE_BYTES
    ):
        return

    data = record.model_dump(mode="json")
    if _LLM_TRACE_CONTENT_REDACT:
        data = redact_trace_data(data)
    line = json.dumps(data, ensure_ascii=False, default=str)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path = file_path.with_suffix(".idx")
    with open(file_path, "a", encoding="utf-8") as f:
        offset = f.tell()
        f.write(line + "\n")
        f.flush()  # 确保 JSONL 落盘后再写 idx，缩小崩溃窗口
        if record.trace_id:
            with open(idx_path, "a", encoding="utf-8") as f_idx:
                f_idx.write(
                    json.dumps({"trace_id": record.trace_id, "offset": offset}, ensure_ascii=False)
                    + "\n"
                )

    from argus_py.observability.trace_index import _cache_invalidate

    _cache_invalidate(file_path)
