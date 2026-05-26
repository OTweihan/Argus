import asyncio

import pytest
from argus_py.core.exceptions import LLMTransientError
from argus_py.llm.client import LLMClient, set_llm_semaphore
from argus_py.llm.models import ChatMessage, ChatResponse
from argus_py.llm.retry import RetryConfig


class _RetryingClient(LLMClient):
    def __init__(self) -> None:
        super().__init__(api_key="sk-test", max_retries=1)
        self.retry_config = RetryConfig(max_retries=1, base_delay_seconds=0.05, max_delay_seconds=0.05)
        self.first_attempt_failed = asyncio.Event()
        self.calls: list[str] = []

    async def _post_completion(self, request):
        content = request.messages[0].content
        self.calls.append(content)
        if content == "first" and self.calls.count("first") == 1:
            self.first_attempt_failed.set()
            raise LLMTransientError("temporary")
        return ChatResponse(content=f"ok-{content}", model="fake")


@pytest.mark.asyncio
async def test_llm_retry_backoff_does_not_hold_global_semaphore(monkeypatch):
    client = _RetryingClient()
    set_llm_semaphore(asyncio.Semaphore(1))
    monkeypatch.setattr("argus_py.llm.retry.random.uniform", lambda _min, _max: 0.05)

    try:
        first = asyncio.create_task(client.chat([ChatMessage(role="user", content="first")]))
        await asyncio.wait_for(client.first_attempt_failed.wait(), 1)

        second = asyncio.create_task(client.chat([ChatMessage(role="user", content="second")]))
        second_response = await asyncio.wait_for(second, 1)

        first_response = await asyncio.wait_for(first, 1)

        assert second_response.content == "ok-second"
        assert first_response.content == "ok-first"
    finally:
        set_llm_semaphore(None)
