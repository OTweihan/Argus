"""FastAPI 应用实例。"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from argus_py.api.auth import DEFAULT_PROTECTED_PREFIXES, AuthTokenMiddleware
from argus_py.api.dependencies import get_task_worker
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
from argus_py.observability.context import set_io_executor
from argus_py.observability.events import STATUS_ERROR, log_event
from argus_py.runtime.container import create_container, shutdown_container
from argus_py.utils.logger import setup_logging

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
# 启用可选 API Token 鉴权的环境变量名。
# 未设置或为空字符串 → 中间件不挂载，向后兼容。
AUTH_TOKEN_ENV = "ARGUS_API_TOKEN"


def _warn_if_multi_worker() -> None:
    """如果检测到多 worker env，打 ERROR 日志（无法阻止多进程启动，但会被运维注意到）。

    CLI ``argus serve`` 会在更早一步拒启；这里是兜底，防止有人直接
    ``uvicorn argus_py.api.app:app --workers N`` 绕过 CLI。多 worker 下
    每个进程都会执行一次本日志，运维一定能从启动日志里发现。
    """
    for env_name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = os.getenv(env_name)
        if not raw:
            continue
        try:
            count = int(raw)
        except ValueError:
            continue
        if count > 1:
            logger.error(
                "检测到 %s=%s，Argus 不支持多 worker 部署："
                "进程内任务队列与 EventBus 不跨进程共享，会出现任务双发和 WS 事件丢失。"
                "请改用单 worker，通过 config/server.yaml 的 scheduler.concurrency 调大并发。",
                env_name,
                count,
            )
            return


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册路由。"""
    setup_logging()
    settings = load_server_settings()
    load_settings().ensure_output_dirs()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """管理后台任务 Worker 与 LLM trace writer 生命周期。"""
        _warn_if_multi_worker()
        ensure_fernet_key(_DefaultDBProbe(DEFAULT_DB_PATH))
        try:
            c = create_container()
            recover_interrupted_tasks(lifecycle=c.lifecycle_service, reader=c.task_read_service)
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
                start_trace_writer(
                    max_queue_size=settings.llm_trace_writer_queue_size,
                    flush_interval_seconds=settings.llm_trace_writer_flush_interval,
                    batch_size=settings.llm_trace_writer_batch_size,
                )
        executor = ThreadPoolExecutor(
            max_workers=min(32, (os.cpu_count() or 1) * 4),
            thread_name_prefix="argus-io",
        )
        asyncio.get_running_loop().set_default_executor(executor)
        set_io_executor(executor)
        await get_task_worker().start()
        try:
            yield
        finally:
            await get_task_worker().stop(settings.scheduler_shutdown_timeout_seconds)
            await shutdown_container()
            # writer 先 stop 以 flush 残留 trace；超时 5s 与 worker 一致。
            stop_trace_writer(timeout=settings.scheduler_shutdown_timeout_seconds)

    application = FastAPI(
        title=f"{PROJECT_NAME} API",
        description=PROJECT_TAGLINE,
        version=PROJECT_VERSION,
        lifespan=lifespan,
    )
    configure_middleware(application, settings)

    auth_token = (os.getenv(AUTH_TOKEN_ENV) or "").strip()
    if auth_token:
        # token 中间件放在最末 add → 最外层执行：未通过校验时不消耗下游限流桶。
        application.add_middleware(AuthTokenMiddleware, token=auth_token)
        logger.info(
            "API Token 鉴权已启用（受保护前缀：%s）",
            ",".join(DEFAULT_PROTECTED_PREFIXES),
        )

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
