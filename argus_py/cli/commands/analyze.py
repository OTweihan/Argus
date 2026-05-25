"""创建并执行白盒分析任务。"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from argus_py.cli.io import cli_cancelled, cli_error, cli_info, cli_print, cli_success
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import TaskError
from argus_py.execution.runner import TaskRunner
from argus_py.runtime.container import create_container
from argus_py.task.application import TaskApplicationService

if TYPE_CHECKING:
    from argus_py.task.models import Task
    from argus_py.task.read import TaskReadService


def build_parser(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """添加 analyze 子命令解析器。"""
    parser = subparsers.add_parser("analyze", help="执行白盒代码分析任务")
    parser.add_argument(
        "--repo",
        help="Git 仓库 URL（与 --source-path 二选一）",
    )
    parser.add_argument(
        "--source-path",
        help="本地源码目录路径（与 --repo 二选一）",
    )
    parser.add_argument(
        "--branch",
        help="Git 仓库分支名（仅对 --repo 有效）",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "endpoints", "callgraph"),
        default="all",
        help="分析范围：all=完整分析，endpoints=仅抽接口，callgraph=仅调用图（默认 all）",
    )
    parser.add_argument("--project", help="关联项目 ID")
    parser.add_argument(
        "--maven-classpath-file",
        help="classpath 文件路径（相对于项目根目录）",
    )
    parser.add_argument(
        "--maven-executable",
        help="Maven 可执行文件路径",
    )
    parser.add_argument(
        "--maven-settings",
        help="Maven settings.xml 路径",
    )
    parser.add_argument(
        "--local-repository",
        help="本地 Maven 仓库路径",
    )
    parser.add_argument(
        "--maven-offline",
        action="store_true",
        help="Maven 离线模式",
    )
    parser.add_argument(
        "--classpath-mode",
        choices=("auto", "cache-only", "maven", "source-only"),
        default=None,
        help="类路径策略：auto（智能降级）、cache-only（仅缓存）、maven（强制 Maven）、source-only（仅源码）",
    )
    parser.add_argument(
        "--prepare-reactor",
        action="store_true",
        help="类路径生成前执行 mvn install -DskipTests（准备 reactor 内部模块）",
    )


async def run(args: argparse.Namespace) -> int:
    """创建并执行白盒分析任务。"""
    c = create_container()
    app = TaskApplicationService(
        lifecycle=c.lifecycle_service,
        task_read=c.task_read_service,
        queue=c.task_queue,
        project_service=c.project_service,
        model_config_service=c.model_config_service,
    )

    repo = getattr(args, "repo", None)
    source_path = getattr(args, "source_path", None)
    branch = getattr(args, "branch", None)
    scope = getattr(args, "scope", "all")
    project_id = getattr(args, "project", None)
    maven_classpath_file = getattr(args, "maven_classpath_file", None)
    maven_executable = getattr(args, "maven_executable", None)
    maven_settings = getattr(args, "maven_settings", None)
    local_repository = getattr(args, "local_repository", None)
    maven_offline = getattr(args, "maven_offline", False)
    classpath_mode = getattr(args, "classpath_mode", None)
    prepare_reactor = getattr(args, "prepare_reactor", False)

    if not repo and not source_path:
        cli_error(
            "白盒分析失败",
            "必须指定 --repo 或 --source-path",
            "示例：argus analyze --repo https://github.com/user/project.git\n"
            "      argus analyze --source-path /path/to/project",
        )
        return 1

    parameters: dict[str, object] = {
        "scope": scope,
    }
    if repo:
        parameters["repo_url"] = repo
    if source_path:
        parameters["source_path"] = source_path
    if branch:
        parameters["branch"] = branch

    maven_config: dict[str, object] = {}
    if maven_classpath_file:
        maven_config["classpathFile"] = maven_classpath_file
    if maven_executable:
        maven_config["executable"] = maven_executable
    if maven_settings:
        maven_config["settingsXml"] = maven_settings
    if local_repository:
        maven_config["localRepository"] = local_repository
    if maven_offline:
        maven_config["offline"] = True
    if classpath_mode:
        maven_config["classpathMode"] = classpath_mode
    if prepare_reactor:
        maven_config["prepareReactorArtifacts"] = True
    if maven_config:
        parameters["maven"] = maven_config

    params = app.resolve_create_params(
        goal="白盒分析",
        start_url=None,
        task_type=TaskType.WHITEBOX,
        project_id=project_id,
        parameters=parameters,
    )

    task = app.create_task(**params)
    cli_success(f"已创建白盒分析任务：{task.task_id}")
    cli_info(f"分析范围：{scope}")
    if repo:
        cli_info(f"仓库：{repo}")
    if source_path:
        cli_info(f"源码路径：{source_path}")

    runner = TaskRunner(
        lifecycle=c.lifecycle_service,
        reader=c.task_read_service,
        model_config_service=c.model_config_service,
    )

    cli_info("开始执行白盒分析...")
    try:
        result = await runner.run(task)
    except TaskError as exc:
        latest = _load_latest_task(c.task_read_service, task)
        _print_result(latest)
        cli_error("白盒分析失败", exc)
        return 1
    except KeyboardInterrupt:
        latest = c.lifecycle_service.cancel_task(task.task_id)
        _print_result(latest)
        cli_cancelled("白盒分析")
        return 130

    _print_result(result)
    return 0


def _load_latest_task(reader: TaskReadService, task: Task) -> Task:
    """读取最新任务快照。"""
    from argus_py.core.exceptions import TaskError as _TaskError

    try:
        return reader.get_task(task.task_id)
    except _TaskError:
        return task


def _print_result(task: Task) -> None:
    """输出白盒分析结果。"""
    cli_print(f"任务 ID：{task.task_id}")
    cli_print(f"任务状态：{task.status.value}")
    cli_print(f"问题数量：{len(task.findings)}")
    if task.result_summary:
        cli_print(f"结果摘要：{task.result_summary}")
    if task.report_path:
        cli_print(f"HTML 报告：{task.report_path}")
    if task.error_message:
        cli_print(f"错误信息：{task.error_message}")
