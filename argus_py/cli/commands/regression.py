"""回归批次 CLI：argus regression run / status / baseline set。

执行模型（与 Web/API 一致）：CLI 只负责向**运行中的 Argus 服务**提交批次
并轮询状态——任务队列是进程内的，只有服务进程的 Worker 会消费。服务未
启动时明确报错，而不是静默等待。

非通过批次返回非零退出码，方便 CI 调用。
"""

from __future__ import annotations

import argparse
import os
import time
from typing import TYPE_CHECKING, Any

import httpx
from argus_py.cli.io import cli_error, cli_info, cli_success, cli_warn
from argus_py.config.server_settings import load_server_settings

if TYPE_CHECKING:
    from argus_py.cli._types import SubParserAdder

_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
_DEFAULT_WAIT_TIMEOUT_SECONDS = 3600
_DEFAULT_POLL_INTERVAL_SECONDS = 2


def build_parser(subparsers: "SubParserAdder") -> None:
    """添加 regression 子命令解析器。"""
    from argus_py.cli.utils import positive_int

    parser = subparsers.add_parser("regression", help="项目级回归测试闭环")
    parser.add_argument(
        "--base-url",
        help="Argus 服务地址（默认 http://127.0.0.1:<config 端口>）",
    )
    sub = parser.add_subparsers(dest="regression_command")

    run_p = sub.add_parser("run", help="发起回归批次并等待结论")
    run_p.add_argument("--project", required=True, help="项目 ID")
    run_p.add_argument(
        "--wait-timeout",
        type=positive_int,
        default=_DEFAULT_WAIT_TIMEOUT_SECONDS,
        help=f"等待批次终态的超时秒数（默认 {_DEFAULT_WAIT_TIMEOUT_SECONDS}）",
    )
    run_p.add_argument(
        "--interval",
        type=positive_int,
        default=_DEFAULT_POLL_INTERVAL_SECONDS,
        help=f"轮询间隔秒数（默认 {_DEFAULT_POLL_INTERVAL_SECONDS}）",
    )

    status_p = sub.add_parser("status", help="查询批次状态")
    status_p.add_argument("run_id", help="批次 ID")

    baseline_p = sub.add_parser("baseline", help="管理项目基线")
    baseline_sub = baseline_p.add_subparsers(dest="baseline_command")
    set_p = baseline_sub.add_parser("set", help="将成功批次设为项目基线")
    set_p.add_argument("run_id", help="批次 ID（必须已 completed）")


def _resolve_base_url(explicit: str | None) -> str:
    if explicit:
        return explicit.rstrip("/")
    settings = load_server_settings()
    host = settings.host
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{settings.port}"


def _client(base_url: str) -> httpx.Client:
    headers: dict[str, str] = {}
    token = (os.getenv("ARGUS_API_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url, timeout=30, headers=headers)


def _extract_error(payload: dict[str, Any]) -> str:
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        code = err.get("code", "")
        message = err.get("message", "")
        return f"{code}: {message}" if code else str(message)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or payload)
    return str(payload or "请求失败")


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        resp = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        cli_error("无法连接 Argus 服务", exc)
        raise SystemExit(2) from exc
    if resp.status_code >= 400:
        cli_error(f"服务返回 {resp.status_code}", _extract_error(_safe_json(resp)))
        raise SystemExit(1) from None
    data = _safe_json(resp)
    return data if isinstance(data, dict) else {}


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {}


def run_run(args: argparse.Namespace) -> int:
    """提交回归批次并轮询至终态；门禁不通过返回 1。"""
    base = _resolve_base_url(getattr(args, "base_url", None))
    interval = max(1, int(args.interval))
    with _client(base) as client:
        created = _request(
            client,
            "POST",
            f"/argus/api/projects/{args.project}/regression-runs",
            json={},
        )
        run_id = created.get("runId")
        if not run_id:
            cli_error("批次创建失败", f"响应缺少 runId：{created}")
            return 1
        cli_success(f"已创建回归批次：{run_id}")
        cli_info(f"轮询批次状态（间隔 {interval}s，超时 {args.wait_timeout}s）...")

        deadline = time.monotonic() + args.wait_timeout
        while True:
            run = _request(client, "GET", f"/argus/api/regression-runs/{run_id}")
            status_value = str(run.get("status", ""))
            if status_value in _TERMINAL_RUN_STATUSES:
                summary = _request(client, "GET", f"/argus/api/regression-runs/{run_id}/summary")
                _print_run(run)
                _print_summary(summary)
                return 1 if not (status_value == "completed" and gate_passed(run)) else 0
            if time.monotonic() >= deadline:
                cli_warn(
                    f"等待超时（{args.wait_timeout}s），批次仍在 {status_value or 'pending'}。"
                    f"可稍后使用 `argus regression status {run_id}` 查看结果。"
                )
                return 1
            time.sleep(interval)


def gate_passed(run: dict[str, Any]) -> bool:
    """批次是否通过质量门禁（仅 completed + passed 视为通过）。"""
    return bool(run.get("status") == "completed" and run.get("gateResult") == "passed")


def run_status(args: argparse.Namespace) -> int:
    """查询单个批次的状态与汇总。"""
    base = _resolve_base_url(getattr(args, "base_url", None))
    with _client(base) as client:
        run = _request(client, "GET", f"/argus/api/regression-runs/{args.run_id}")
        _print_run(run)
        summary_resp = _request(client, "GET", f"/argus/api/regression-runs/{args.run_id}/summary")
        _print_summary(summary_resp)
    return 0 if gate_passed(run) else (1 if run.get("status") in _TERMINAL_RUN_STATUSES else 0)


def run_baseline_set(args: argparse.Namespace) -> int:
    """将成功批次设为其项目的基线。"""
    base = _resolve_base_url(getattr(args, "base_url", None))
    project_id: str | None = None
    with _client(base) as client:
        run = _request(client, "GET", f"/argus/api/regression-runs/{args.run_id}")
        project_id = str(run.get("projectId") or "")
        if not project_id:
            cli_error("设置基线失败", f"无法解析批次所属项目：{run}")
            return 1
        _request(
            client,
            "PUT",
            f"/argus/api/projects/{project_id}/regression-baseline",
            json={"runId": args.run_id},
        )
    cli_success(f"已将批次 {args.run_id} 设为项目 {project_id} 的基线。")
    return 0


def _print_run(run: dict[str, Any]) -> None:
    print("")
    cli_success(
        f"批次 {run.get('runId')}："
        f"status={run.get('status')} gate={run.get('gateResult') or '-'} "
        f"baseline={run.get('baselineRunId') or '-'}"
    )
    if run.get("errorMessage"):
        cli_warn(str(run["errorMessage"]))


def _print_summary(summary: dict[str, Any]) -> None:
    if not summary:
        return
    counts = summary.get("itemCounts") or {}
    totals = summary.get("findingTotals") or {}
    diff = summary.get("diff") or {}
    reasons = summary.get("blockingReasons") or []
    cli_info(
        "用例：{total} 个（完成 {completed} / 失败 {failed} / 超时 {timeout} / 取消 {cancelled} / 跳过 {skipped}）".format(
            total=counts.get("total", "?"),
            completed=counts.get("completed", 0),
            failed=counts.get("failed", 0),
            timeout=counts.get("timeout", 0),
            cancelled=counts.get("cancelled", 0),
            skipped=counts.get("skipped", 0),
        )
    )
    cli_info(
        f"问题：当前 {totals.get('current', '?')} 个，基线 {totals.get('baseline', '?')} 个；"
        f"新增 {diff.get('addedCount', 0)}、持续 {diff.get('persistentCount', 0)}、"
        f"已解决 {diff.get('resolvedCount', 0)}"
    )
    for reason in reasons:
        cli_warn(f"阻断原因：{reason}")
