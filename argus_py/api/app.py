"""FastAPI 应用实例。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from argus_py.api.dependencies import get_task_service, get_task_worker
from argus_py.api.middleware import configure_middleware
from argus_py.api.routes import (
    config,
    events,
    health,
    projects,
    prompts,
    reports,
    tasks,
    ws,
)
from argus_py.config.server_settings import load_server_settings
from argus_py.config.settings import load_settings
from argus_py.core.constants import PROJECT_NAME, PROJECT_TAGLINE, PROJECT_VERSION
from argus_py.core.crypto import ensure_fernet_key
from argus_py.core.paths import API_STATIC_DIR, OUTPUT_DIR
from argus_py.infra.db import DEFAULT_DB_PATH, _DefaultDBProbe
from argus_py.infra.recovery import recover_interrupted_tasks
from argus_py.infra.temp_cleanup import cleanup_stale_debug_bundles
from argus_py.observability import (
    cleanup_old_traces,
    start_trace_writer,
    stop_trace_writer,
)
from argus_py.observability.events import STATUS_ERROR, log_event
from argus_py.utils.logger import setup_logging

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册路由。"""
    setup_logging()
    settings = load_server_settings()
    load_settings().ensure_output_dirs()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """管理后台任务 Worker 与 LLM trace writer 生命周期。"""
        ensure_fernet_key(_DefaultDBProbe(DEFAULT_DB_PATH))
        try:
            recover_interrupted_tasks(get_task_service())
        except Exception:
            log_event(logger, "lifespan.recover_tasks", status=STATUS_ERROR, exc_info=True)
        try:
            cleanup_stale_debug_bundles()
        except Exception:
            log_event(logger, "lifespan.cleanup_bundles", status=STATUS_ERROR, exc_info=True)
        if settings.llm_trace_enabled:
            try:
                cleanup_old_traces(
                    OUTPUT_DIR / "traces",
                    retention_days=settings.llm_trace_retention_days,
                    total_size_mb=settings.llm_trace_total_size_mb,
                )
            except Exception:
                log_event(logger, "lifespan.cleanup_traces", status=STATUS_ERROR, exc_info=True)
            if settings.llm_trace_async_writer:
                start_trace_writer(max_queue_size=settings.llm_trace_writer_queue_size)
        await get_task_worker().start()
        try:
            yield
        finally:
            await get_task_worker().stop(settings.scheduler_shutdown_timeout_seconds)
            # writer 先 stop 以 flush 残留 trace；超时 5s 与 worker 一致。
            stop_trace_writer(timeout=settings.scheduler_shutdown_timeout_seconds)

    application = FastAPI(
        title=f"{PROJECT_NAME} API",
        description=PROJECT_TAGLINE,
        version=PROJECT_VERSION,
        lifespan=lifespan,
    )
    configure_middleware(application, settings)

    application.include_router(health.router)
    application.include_router(projects.router, prefix=API_PREFIX)
    application.include_router(tasks.router, prefix=API_PREFIX)
    application.include_router(reports.router, prefix=API_PREFIX)
    application.include_router(config.router, prefix=API_PREFIX)
    application.include_router(events.router, prefix=API_PREFIX)
    application.include_router(prompts.router, prefix=API_PREFIX)
    application.include_router(ws.router, prefix=API_PREFIX)
    if (API_STATIC_DIR / "index.html").exists():
        application.mount(
            "/",
            StaticFiles(directory=API_STATIC_DIR, html=True),
            name="console",
        )
    return application


app = create_app()
