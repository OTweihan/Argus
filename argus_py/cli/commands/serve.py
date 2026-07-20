"""启动 FastAPI Web 服务。"""

from __future__ import annotations

import argparse
import os
from typing import TYPE_CHECKING

from argus_py.cli.io import cli_cancelled, cli_error, cli_info
from argus_py.config.server_settings import SERVER_CONFIG_ENV, load_server_settings
from argus_py.core.paths import resolve_project_path

if TYPE_CHECKING:
    from argus_py.cli._types import SubParserAdder

_MULTI_WORKER_ENV_VARS = ("WEB_CONCURRENCY", "UVICORN_WORKERS")


def _detect_multi_worker_env() -> tuple[str, int] | None:
    """检测环境变量是否要求多 worker。返回 (env 名, 数量) 或 None。

    Argus 使用进程内 asyncio.Queue 作为任务队列、进程内 EventBus 推送 WebSocket
    事件，多 worker 部署会出现：
    - 同一任务被多个 worker 同时消费（任务双发）
    - WebSocket 事件只能广播到当前进程的订阅者（前端事件丢失约 1 - 1/N）
    - lru_cache 单例分裂，依赖注入状态不一致

    要扩展副本需要先把 queue / event 切到外置（Redis、NATS 等）。当前阶段
    直接拒启，避免运维误把 K8s replicas 调大引发数据/事件不一致。
    """
    for env_name in _MULTI_WORKER_ENV_VARS:
        raw = os.getenv(env_name)
        if not raw:
            continue
        try:
            count = int(raw)
        except ValueError:
            continue
        if count > 1:
            return env_name, count
    return None


def build_parser(subparsers: "SubParserAdder") -> None:
    """添加 serve 子命令解析器。"""
    parser = subparsers.add_parser("serve", help="启动 FastAPI Web 服务")
    parser.add_argument("--host", help="监听地址；不传时读取 config/server.yaml")
    parser.add_argument("--port", type=int, help="监听端口；不传时读取 config/server.yaml")
    parser.add_argument("--reload", action="store_true", default=None, help="启用开发热重载")
    parser.add_argument("--config", default="config/server.yaml", help="服务配置文件路径")


def run(args: argparse.Namespace) -> int:
    """启动 FastAPI Web 服务。"""
    try:
        import uvicorn
    except ImportError:
        cli_error(
            "Web 服务启动失败",
            "缺少 uvicorn 依赖。",
            '请先安装项目依赖，例如：pip install -e ".[dev]"',
        )
        return 1

    multi_worker = _detect_multi_worker_env()
    if multi_worker is not None:
        env_name, count = multi_worker
        cli_error(
            "Web 服务启动被拒绝",
            f"检测到 {env_name}={count}，Argus 当前不支持多 worker 部署。",
            "原因：进程内任务队列与 EventBus 不跨进程共享，会导致任务双发、WS 事件丢失。\n"
            "建议：保持单 worker，通过 config/server.yaml 的 scheduler.concurrency 调大单进程并发；"
            f"或先 unset {env_name} 后重启。",
        )
        return 1

    os.environ[SERVER_CONFIG_ENV] = str(resolve_project_path(args.config))
    settings = load_server_settings(args.config)
    host = args.host or settings.host
    port = args.port or settings.port
    reload_enabled = args.reload if args.reload is not None else settings.reload

    cli_info(f"启动 Web 服务：http://{host}:{port}")
    cli_info("OpenAPI 文档：/docs")
    try:
        uvicorn.run(
            "argus_py.api.app:app",
            host=host,
            port=port,
            reload=reload_enabled,
            access_log=False,
        )
    except KeyboardInterrupt:
        cli_cancelled("Web 服务")
        return 130
    return 0
