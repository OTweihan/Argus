"""LLM client for calling Dashscope / OpenAI-compatible APIs."""

import os
from typing import Any, Dict, List, Optional

import httpx

from argus_py.core.constants import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
)
from argus_py.core.exceptions import ConfigError, LLMError
from argus_py.llm.models import ChatMessage, ChatResponse


class LLMClient:
    """OpenAI-compatible API client (supports Dashscope, OpenAI, etc.)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_LLM_MODEL,
        max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        temperature: float = DEFAULT_LLM_TEMPERATURE,
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise ConfigError("LLM_API_KEY is not set. Provide it via env or constructor.")

        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def chat(
        self,
        messages: List[ChatMessage],
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        """Send a chat completion request.

        Args:
            messages: List of chat messages.
            response_format: Optional JSON schema for structured output.

        Returns:
            ChatResponse with parsed content.

        Raises:
            LLMError: On API failure.
        """
        # TODO: Implement httpx POST to {base_url}/chat/completions
        # TODO: Handle rate limits with retry
        # TODO: Parse response into ChatResponse
        raise NotImplementedError("LLMClient.chat() not yet implemented")
