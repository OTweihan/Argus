"""LLM 调用追踪记录。"""

from __future__ import annotations

import json
import logging
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

# ── 脱敏配置 ──────────────────────────────────────────────
# 匹配到这些 key 时值被脱敏（精确匹配，不含子串）
_SENSITIVE_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "cookie", "password", "secret", "token"}
)
# 即使在敏感 dict 内也保留的诊断字段
_SAFELIST_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens", "token_usage"})

MASK = "***"


def _redact_trace_data(data: dict[str, Any]) -> dict[str, Any]:
    """递归脱敏敏感字段，诊断字段豁免。"""

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
        return value

    return _recurse(data)


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
    """
    if not record.task_id:
        logger.warning(
            "LLM 追踪记录缺少 task_id，已丢弃：phase=%s event=%s", record.phase, record.event
        )
        return
    traces_dir = OUTPUT_DIR / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    file_path = traces_dir / f"{record.task_id}.jsonl"

    data = asdict(record)
    redacted = _redact_trace_data(data)

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(redacted, ensure_ascii=False, default=str) + "\n")
