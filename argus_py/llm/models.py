"""LLM 请求和响应数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ChatMessage:
    """OpenAI Chat Completions 消息。"""

    role: MessageRole
    content: str

    def to_dict(self) -> dict[str, str]:
        """转换为 OpenAI 兼容消息格式。"""
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class TokenUsage:
    """Token 使用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        """从 API usage 字段构建。"""
        data = data or {}
        return cls(
            prompt_tokens=int(data.get("prompt_tokens") or 0),
            completion_tokens=int(data.get("completion_tokens") or 0),
            total_tokens=int(data.get("total_tokens") or 0),
        )

    def to_dict(self) -> dict[str, int]:
        """转换为 dict。"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class ChatCompletionRequest:
    """OpenAI Chat Completions 请求。"""

    model: str
    messages: list[ChatMessage]
    temperature: float = 0.1
    max_tokens: int = 4096
    response_format: dict[str, Any] | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """转换为 OpenAI 兼容请求体。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_dict() for message in self.messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.response_format:
            payload["response_format"] = self.response_format
        payload.update(self.extra_body)
        return payload


@dataclass(frozen=True)
class ChatResponse:
    """聊天补全响应。"""

    content: str
    model: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None
    response_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai_response(cls, data: dict[str, Any], fallback_model: str = "") -> "ChatResponse":
        """从 OpenAI 兼容响应解析文本。"""
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM 响应缺少 choices。")

        first = choices[0]
        message = first.get("message") or {}
        content = message.get("content")
        if content is None:
            content = first.get("text", "")

        return cls(
            content=str(content or ""),
            model=str(data.get("model") or fallback_model),
            usage=TokenUsage.from_dict(data.get("usage")),
            finish_reason=first.get("finish_reason"),
            response_id=data.get("id"),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为 dict。"""
        return {
            "content": self.content,
            "model": self.model,
            "usage": self.usage.to_dict(),
            "finish_reason": self.finish_reason,
            "response_id": self.response_id,
        }
