"""OpenAI Completions 格式兼容 LLM 客户端。"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from argus_py.core.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
)
from argus_py.core.exceptions import ConfigError, LLMError, LLMRateLimitError
from argus_py.llm.models import ChatCompletionRequest, ChatMessage, ChatResponse
from argus_py.llm.retry import RetryConfig, retry_async


class LLMClient:
    """OpenAI Chat Completions 兼容客户端。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        temperature: float = DEFAULT_LLM_TEMPERATURE,
        timeout_seconds: float = 120.0,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
        completions_path: str = "/chat/completions",
    ) -> None:
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        if not self.api_key:
            raise ConfigError("API Key 未配置。请先执行：argus config llm")
        self.base_url = str(base_url or os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.retry_config = RetryConfig(max_retries=max_retries)
        self.completions_path = (
            completions_path if completions_path.startswith("/") else f"/{completions_path}"
        )

    @property
    def completions_url(self) -> str:
        """OpenAI 兼容 completions URL。"""
        return f"{self.base_url}{self.completions_path}"

    async def chat(
        self,
        messages: list[ChatMessage],
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
        _trace_ctx: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """发送 OpenAI Chat Completions 请求。

        _trace_ctx — 若传入，会在调用完成后补充底层信息
        （model、base_url_host、latency_ms、token_usage、error）。
        """
        request = ChatCompletionRequest(
            model=self.model or DEFAULT_LLM_MODEL,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=response_format,
            extra_body=extra_body or {},
        )
        start = time.monotonic()
        try:
            response = await retry_async(
                lambda: self._post_completion(request),
                retry_config=self.retry_config,
                retryable_errors=(LLMRateLimitError, LLMError),
            )
        except Exception as exc:
            if _trace_ctx is not None:
                _trace_ctx.setdefault("latency_ms", (time.monotonic() - start) * 1000)
                _trace_ctx.setdefault("error", str(exc))
                _trace_ctx.setdefault("base_url_host", self._parse_host())
            raise

        if _trace_ctx is not None:
            _trace_ctx.setdefault("latency_ms", (time.monotonic() - start) * 1000)
            _trace_ctx.setdefault("model", response.model)
            _trace_ctx.setdefault(
                "token_usage",
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            )
            _trace_ctx.setdefault("base_url_host", self._parse_host())
        return response

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
        _trace_ctx: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """使用单条 Prompt 发起补全。"""
        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))
        return await self.chat(
            messages,
            response_format=response_format,
            extra_body=extra_body,
            _trace_ctx=_trace_ctx,
        )

    def _parse_host(self) -> str:
        """从 base_url 中提取 host。"""
        stripped = self.base_url.split("://")[-1]
        return stripped.split("/")[0] if "/" in stripped else stripped

    async def _post_completion(self, request: ChatCompletionRequest) -> ChatResponse:
        """提交请求并解析 OpenAI 兼容响应。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.completions_url,
                    headers=headers,
                    json=request.to_payload(),
                )
        except httpx.TimeoutException as exc:
            raise LLMError(f"LLM 请求超时：{exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 请求失败：{exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError("LLM 请求被限流。")
        if response.status_code >= 500:
            raise LLMError(f"LLM 服务端异常：HTTP {response.status_code} {response.text}")
        if response.status_code in {401, 403}:
            raise ConfigError(f"LLM 鉴权失败：HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ConfigError(f"LLM 请求参数异常：HTTP {response.status_code} {response.text}")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(f"LLM 响应不是有效 JSON：{response.text}") from exc

        try:
            return ChatResponse.from_openai_response(
                data, fallback_model=self.model or DEFAULT_LLM_MODEL
            )
        except ValueError as exc:
            raise LLMError(str(exc)) from exc
