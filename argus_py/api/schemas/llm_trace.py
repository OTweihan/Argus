"""LLM 追踪 API Schema，统一 snake_case → camelCase 输出。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from argus_py.api.schemas.base import ApiModel


class LLMTraceResponse(ApiModel):
    """LLM 追踪记录响应模型。"""

    trace_id: str = Field(default="", alias="traceId")
    task_id: str = Field(default="", alias="taskId")
    phase: str = ""
    event: str = ""
    system_prompt: str = Field(default="", alias="systemPrompt")
    input_payload: dict[str, Any] = Field(default_factory=dict, alias="inputPayload")
    model: str = ""
    base_url_host: str = Field(default="", alias="baseUrlHost")
    latency_ms: float = Field(default=0.0, alias="latencyMs")
    token_usage: dict[str, int] = Field(default_factory=dict, alias="tokenUsage")
    raw_response: str = Field(default="", alias="rawResponse")
    parsed_result: Any = Field(default=None, alias="parsedResult")
    parse_error: str = Field(default="", alias="parseError")
    error: str = ""
    timestamp: str = ""
