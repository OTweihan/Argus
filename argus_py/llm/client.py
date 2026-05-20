"""OpenAI Completions 格式兼容 LLM 客户端。"""

from __future__ import annotations

import asyncio
import logging
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
from argus_py.core.exceptions import (
    ConfigError,
    LLMError,
    LLMRateLimitError,
    LLMTransientError,
)
from argus_py.llm.models import ChatCompletionRequest, ChatMessage, ChatResponse
from argus_py.llm.retry import RetryConfig, retry_async

logger = logging.getLogger(__name__)


# 进程级 LLM 并发信号量（由容器在 startup 设置）。None = 不限。
_llm_semaphore: asyncio.Semaphore | None = None


def set_llm_semaphore(sem: asyncio.Semaphore) -> None:
    """设置全局 LLM 并发信号量。"""
    global _llm_semaphore
    _llm_semaphore = sem


class LLMClient:
    """OpenAI Chat Completions 兼容客户端。

    单实例内部复用同一个 ``httpx.AsyncClient``：保持 keep-alive 连接池，
    避免每次 ``chat`` / ``complete`` 都重做 TCP / TLS 握手。
    生命周期由调用方负责 —— 用完请调用 ``aclose()``，或使用 ``async with``。
    """

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
        httpx_proxy: str | None = None,
        httpx_trust_env: bool | None = None,
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
        # 代理配置（不显式传入时回落到环境变量，再回落到 httpx 默认行为）：
        # - LLM_HTTPX_PROXY: 显式 proxy URL，例如 ``http://user:pass@host:port``
        # - LLM_HTTPX_TRUST_ENV: ``"0"`` / ``"false"`` 关闭 httpx 默认的 HTTP(S)_PROXY 环境变量探测
        self._httpx_proxy = httpx_proxy if httpx_proxy is not None else os.getenv("LLM_HTTPX_PROXY")
        if httpx_trust_env is None:
            env_trust = os.getenv("LLM_HTTPX_TRUST_ENV", "").strip().lower()
            self._httpx_trust_env = env_trust not in {"0", "false", "no", "off"}
        else:
            self._httpx_trust_env = httpx_trust_env
        # httpx.AsyncClient 必须在 async 上下文中关闭；首次请求时懒创建。
        self._http: httpx.AsyncClient | None = None

    @property
    def completions_url(self) -> str:
        """OpenAI 兼容 completions URL。"""
        return f"{self.base_url}{self.completions_path}"

    def _ensure_http(self) -> httpx.AsyncClient:
        """懒创建并复用 httpx.AsyncClient（保持连接池 keep-alive）。

        按 httpx 版本兼容地传入代理参数：httpx 0.28+ 使用单数 ``proxy``，
        旧版本使用 ``proxies``；只在显式配置 proxy 时尝试，避免在不需要代理
        的常态路径触发 TypeError fallback。
        """
        if self._http is not None and not self._http.is_closed:
            return self._http
        kwargs: dict[str, Any] = {
            "timeout": self.timeout_seconds,
            "trust_env": self._httpx_trust_env,
        }
        if self._httpx_proxy:
            try:
                self._http = httpx.AsyncClient(proxy=self._httpx_proxy, **kwargs)
            except TypeError:
                # httpx < 0.28 兼容路径
                legacy_kwargs = dict(kwargs)
                legacy_kwargs["proxies"] = self._httpx_proxy
                self._http = httpx.AsyncClient(**legacy_kwargs)
        else:
            self._http = httpx.AsyncClient(**kwargs)
        return self._http

    async def aclose(self) -> None:
        """显式关闭底层 httpx 连接池。可重复调用。"""
        if self._http is not None and not self._http.is_closed:
            try:
                await self._http.aclose()
            except Exception:  # noqa: BLE001 - 释放阶段不应再抛错
                logger.debug("关闭 LLM httpx 客户端时忽略异常", exc_info=True)
        self._http = None

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object
    ) -> None:
        await self.aclose()

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
        sem = _llm_semaphore
        if sem is not None:
            await sem.acquire()
        try:
            return await self._chat(messages, response_format, extra_body, _trace_ctx)
        finally:
            if sem is not None:
                sem.release()

    async def _chat(
        self,
        messages: list[ChatMessage],
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
        _trace_ctx: dict[str, Any] | None = None,
    ) -> ChatResponse:
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
                retryable_errors=(LLMTransientError,),
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
        client = self._ensure_http()
        try:
            response = await client.post(
                self.completions_url,
                headers=headers,
                json=request.to_payload(),
            )
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"LLM 请求超时：{exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError(f"LLM 请求失败：{exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError("LLM 请求被限流。")
        if response.status_code >= 500:
            raise LLMTransientError(f"LLM 服务端异常：HTTP {response.status_code} {response.text}")
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
