"""LLM data models."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChatMessage:
    """Single chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ChatResponse:
    """Parsed chat completion response."""

    content: str
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "usage": self.usage,
            "finish_reason": self.finish_reason,
        }
