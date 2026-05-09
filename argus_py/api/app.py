"""FastAPI 应用实例。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from argus_py.api.dependencies import get_task_service, get_task_worker, load_server_settings
from argus_py.api.middleware import configure_middleware
from argus_py.api.routes import config, health, projects, reports, tasks, ws
from argus_py.config.settings import load_settings
from argus_py.core.constants import PROJECT_NAME, PROJECT_TAGLINE, PROJECT_VERSION
from argus_py.core.crypto import ensure_fernet_key
from argus_py.core.paths import API_STATIC_DIR
from argus_py.infra.db import DEFAULT_DB_PATH
from argus_py.infra.recovery import recover_interrupted_tasks
from argus_py.utils.logger import setup_logging

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册路由。"""
    setup_logging()
    settings = load_server_settings()
    load_settings().ensure_output_dirs()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """管理后台任务 Worker 生命周期。"""
        ensure_fernet_key(DEFAULT_DB_PATH)
        recover_interrupted_tasks(get_task_service())
        await get_task_worker().start()
        try:
            yield
        finally:
            await get_task_worker().stop(settings.scheduler_shutdown_timeout_seconds)

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
    application.include_router(ws.router, prefix=API_PREFIX)
    if (API_STATIC_DIR / "index.html").exists():
        application.mount(
            "/",
            StaticFiles(directory=API_STATIC_DIR, html=True),
            name="console",
        )
    return application


app = create_app()
