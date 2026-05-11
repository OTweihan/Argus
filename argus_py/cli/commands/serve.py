"""启动 FastAPI Web 服务。"""

from __future__ import annotations

import argparse
import os

from argus_py.cli.utils import print_cli_cancelled, print_cli_error
from argus_py.config.server_settings import SERVER_CONFIG_ENV, load_server_settings
from argus_py.core.paths import resolve_project_path


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
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
        print_cli_error(
            "Web 服务启动失败",
            "缺少 uvicorn 依赖。",
            '请先安装项目依赖，例如：pip install -e ".[dev]"',
        )
        return 1

    os.environ[SERVER_CONFIG_ENV] = str(resolve_project_path(args.config))
    settings = load_server_settings(args.config)
    host = args.host or settings.host
    port = args.port or settings.port
    reload_enabled = args.reload if args.reload is not None else settings.reload

    print(f"启动 Web 服务：http://{host}:{port}")
    print("OpenAPI 文档：/docs")
    try:
        uvicorn.run(
            "argus_py.api.app:app",
            host=host,
            port=port,
            reload=reload_enabled,
            access_log=False,
        )
    except KeyboardInterrupt:
        print_cli_cancelled("Web 服务")
        return 130
    return 0
