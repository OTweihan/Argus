from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from argus_py.config.server_settings import load_server_settings
from argus_py.observability.context import io_executor_stats


@pytest.mark.asyncio
async def test_lifespan_can_restart_without_reusing_runtime_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = import_module("argus_py.api.app")
    settings = replace(load_server_settings(), llm_trace_enabled=False)
    workers = [
        SimpleNamespace(start=AsyncMock(), stop=AsyncMock()),
        SimpleNamespace(start=AsyncMock(), stop=AsyncMock()),
    ]
    shutdown = AsyncMock()
    reset = Mock()

    monkeypatch.setattr(app_module, "setup_logging", Mock())
    monkeypatch.setattr(
        app_module,
        "load_settings",
        lambda: SimpleNamespace(ensure_output_dirs=Mock()),
    )
    monkeypatch.setattr(app_module, "load_server_settings", lambda: settings)
    monkeypatch.setattr(app_module, "ensure_fernet_key", Mock())
    monkeypatch.setattr(app_module, "recover_interrupted_tasks", Mock())
    monkeypatch.setattr(app_module, "cleanup_stale_debug_bundles", Mock())
    monkeypatch.setattr(app_module, "stop_trace_writer", Mock())
    monkeypatch.setattr(
        app_module,
        "create_container",
        lambda: SimpleNamespace(lifecycle_service=Mock(), task_read_service=Mock()),
    )
    monkeypatch.setattr(app_module, "get_task_worker", lambda: workers.pop(0))
    monkeypatch.setattr(app_module, "shutdown_container", shutdown)
    monkeypatch.setattr(app_module, "reset_all_dependencies", reset)

    application = app_module.create_app()
    first, second = workers
    async with application.router.lifespan_context(application):
        assert first.start.await_count == 1
    async with application.router.lifespan_context(application):
        assert second.start.await_count == 1

    first.stop.assert_awaited_once_with(settings.scheduler_shutdown_timeout_seconds)
    second.stop.assert_awaited_once_with(settings.scheduler_shutdown_timeout_seconds)
    assert shutdown.await_count == 2
    assert reset.call_count == 2
    assert io_executor_stats() == {"queued": -1}
