"""诊断中心服务状态聚合（docs/optimizations/diagnostics-center-plan.md 第 7/13/17 章）。

覆盖：Python 进程、Java 分析器（actuator 探测，带 TTL 缓存）、SQLite、
Web 静态资源、日志目录占用、系统信息与概览聚合。同步方法由路由层经
``run_in_thread`` 执行；``java_status`` / 依赖它的异步聚合是异步方法。
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from argus_py.config.server_settings import ServerSettings
from argus_py.core.paths import API_STATIC_DIR, DATA_DIR, LOGS_DIR, OUTPUT_DIR, PROJECT_ROOT
from argus_py.observability.context import get_process_run_id
from argus_py.observability.diagnostics_store import DiagnosticsQuery, FileDiagnosticsLogStore

logger = logging.getLogger(__name__)

# 模块导入时间 ≈ 服务进程启动时间的近似值（app 工厂在进程启动时导入本模块）。
_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_JAVA_CACHE_TTL_SECONDS = 10.0


@dataclass(frozen=True)
class ServiceStatus:
    """单组件状态（wire 字段 camelCase，见方案 7.2）。"""

    name: str
    status: str  # ok / unreachable / unknown / not_ready / not_built
    version: str | None = None
    pid: int | None = None
    port: int | None = None
    host: str | None = None
    started_at: str | None = None
    uptime_seconds: float | None = None
    latency_ms: float | None = None
    detail: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "status": self.status}
        optional = {
            "version": self.version,
            "pid": self.pid,
            "port": self.port,
            "host": self.host,
            "startedAt": self.started_at,
            "uptimeSeconds": self.uptime_seconds,
            "latencyMs": self.latency_ms,
            "detail": self.detail,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})
        return payload


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class DiagnosticsService:
    """聚合各组件健康状态、系统信息与日志目录用量。"""

    def __init__(self, settings: ServerSettings, store: FileDiagnosticsLogStore) -> None:
        self._settings = settings
        self._store = store
        self._java_cache: tuple[float, ServiceStatus] | None = None

    # ── 同步检查（run_in_thread 执行）───────────────────────────────────

    def python_status(self) -> ServiceStatus:
        from argus_py.core.constants import PROJECT_VERSION

        return ServiceStatus(
            name="python",
            status="ok",
            version=PROJECT_VERSION,
            pid=os.getpid(),
            port=self._settings.port,
            host=self._settings.host,
            started_at=_iso(_PROCESS_STARTED_AT),
            uptime_seconds=max(
                0.0, (datetime.now(timezone.utc) - _PROCESS_STARTED_AT).total_seconds()
            ),
        )

    def db_status(self) -> ServiceStatus:
        from argus_py.infra.db import DEFAULT_DB_PATH, connect

        started = time.monotonic()
        try:
            conn = connect(DEFAULT_DB_PATH)
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 — 健康检查必须吞掉异常转状态
            return ServiceStatus(name="database", status="unreachable", detail=str(exc))
        latency = (time.monotonic() - started) * 1000
        return ServiceStatus(
            name="database", status="ok", latency_ms=round(latency, 1), detail=str(DEFAULT_DB_PATH)
        )

    def console_status(self) -> ServiceStatus:
        index_html = API_STATIC_DIR / "index.html"
        status = "ok" if index_html.is_file() else "not_built"
        detail = None if index_html.is_file() else "前端静态资源未构建（frontend dist 未挂载）"
        return ServiceStatus(name="web", status=status, detail=detail)

    def logs_usage(self) -> dict[str, Any]:
        """日志目录空间占用（方案 6.2：概览/系统信息字段）。"""
        root: Path = self._store.logs_root
        total_bytes = 0
        file_count = 0
        if root.is_dir():
            for path in root.rglob("*"):
                try:
                    if path.is_file():
                        total_bytes += path.stat().st_size
                        file_count += 1
                except OSError:
                    continue
        usage: dict[str, str | int] = {
            "path": str(root),
            "totalBytes": total_bytes,
            "fileCount": file_count,
        }
        try:
            usage["freeBytes"] = shutil.disk_usage(root).free
        except OSError:
            pass
        return usage

    def system_info(self) -> dict[str, Any]:
        """系统信息快照（方案 13.2）；路径适度保留，不展开环境变量全文。"""
        from argus_py.core.constants import PROJECT_VERSION

        disk: dict[str, int] = {}
        try:
            usage = shutil.disk_usage(OUTPUT_DIR)
            disk = {
                "totalBytes": usage.total,
                "freeBytes": usage.free,
                "usedBytes": usage.used,
            }
        except OSError:
            pass

        java_runtime_dir = self._store.logs_root / "runtime" / "java"
        java_logs_present = False
        if java_runtime_dir.is_dir():
            try:
                java_logs_present = any(java_runtime_dir.iterdir())
            except OSError:
                java_logs_present = False

        return {
            "argusVersion": PROJECT_VERSION,
            "pythonVersion": sys.version.split()[0],
            "pythonServiceVersion": PROJECT_VERSION,
            "osName": platform.system(),
            "osRelease": platform.release(),
            "architecture": platform.machine(),
            "hostname": local_hostname(),
            "pid": os.getpid(),
            "cpuCount": os.cpu_count(),
            "runId": get_process_run_id(),
            "startedAt": _iso(_PROCESS_STARTED_AT),
            "uptimeSeconds": max(
                0.0, (datetime.now(timezone.utc) - _PROCESS_STARTED_AT).total_seconds()
            ),
            "workingDirectory": str(Path.cwd()),
            "projectRoot": str(PROJECT_ROOT),
            "logsDirectory": str(self._store.logs_root if self._store.logs_root else LOGS_DIR),
            "dataDirectory": str(DATA_DIR),
            "outputDirectory": str(OUTPUT_DIR),
            "deploymentMode": _deployment_mode(self._settings),
            "logDataSource": "file",
            "javaAnalyzerUrl": self._settings.java_analyzer_url,
            "javaRuntimeLogsPresent": java_logs_present,
            "disk": disk or None,
        }

    def recent_error_count(self, hours: float = 1.0, limit_scan: int = 200) -> int:
        """近 N 小时 ERROR 数量近似值（有界扫描，非精确全局计数）。"""
        time_from = datetime.now(timezone.utc) - timedelta(hours=max(0.1, hours))
        page = self._store.search(
            DiagnosticsQuery(level="ERROR", time_from=time_from, limit=max(1, limit_scan))
        )
        return len(page.items)

    def recent_system_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """最近系统事件（component=system），新→旧。"""
        page = self._store.search(
            DiagnosticsQuery(component="system", limit=max(1, min(limit, 100)))
        )
        return [event.to_wire() for event in page.items]

    def overview_sync(self) -> dict[str, Any]:
        """概览同步部分：不含 Java 探测（由异步层合并）。"""
        python = self.python_status()
        db = self.db_status()
        web = self.console_status()
        usage = self.logs_usage()
        try:
            error_count = self.recent_error_count()
        except Exception:  # noqa: BLE001
            logger.debug("概览 ERROR 计数失败", exc_info=True)
            error_count = 0
        try:
            events = self.recent_system_events(limit=10)
        except Exception:  # noqa: BLE001
            logger.debug("概览系统事件读取失败", exc_info=True)
            events = []
        return {
            "runId": get_process_run_id(),
            "services": [python.to_wire(), db.to_wire(), web.to_wire()],
            "logsUsage": usage,
            "errorCountLastHour": error_count,
            "recentSystemEvents": events,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
        }

    # ── 异步探测 ────────────────────────────────────────────────────────

    async def java_status(self) -> ServiceStatus:
        """探测 Java 分析器 actuator health，10s TTL 缓存避免高频穿透。"""
        now = time.monotonic()
        if self._java_cache is not None and now - self._java_cache[0] < _JAVA_CACHE_TTL_SECONDS:
            return self._java_cache[1]

        base_url = self._settings.java_analyzer_url.rstrip("/")
        url = f"{base_url}/actuator/health"
        started = time.monotonic()
        status = ServiceStatus(name="java", status="unknown", detail=None)
        try:
            async with httpx.AsyncClient(
                timeout=min(3.0, max(0.5, self._settings.java_analyzer_request_timeout)),
                # trust_env=False：Windows 系统代理（注册表级，非环境变量）会拦截
                # localhost 探测并返回 502——与 WhiteboxClient 的既有教训一致，
                # 内网健康探测必须绕过代理直连。
                trust_env=False,
            ) as client:
                response = await client.get(url)
            latency = round((time.monotonic() - started) * 1000, 1)
            healthy = response.status_code == 200
            body: Any = None
            try:
                body = response.json()
            except ValueError:
                pass
            summary = None
            if isinstance(body, dict):
                summary = str(body.get("status") or "")
            status = ServiceStatus(
                name="java",
                status="ok" if healthy else "unreachable",
                latency_ms=latency,
                host=_host_of(base_url),
                port=_port_of(base_url),
                detail=f"HTTP {response.status_code}" + (f" {summary}" if summary else ""),
            )
        except Exception as exc:  # noqa: BLE001 — 探测失败是正常状态而非错误
            latency = round((time.monotonic() - started) * 1000, 1)
            status = ServiceStatus(
                name="java",
                status="unreachable",
                latency_ms=latency,
                host=_host_of(base_url),
                port=_port_of(base_url),
                detail=str(exc),
            )
        self._java_cache = (now, status)
        return status


def _deployment_mode(settings: ServerSettings) -> str:
    env_mode = (os.getenv("ARGUS_DEPLOYMENT_MODE") or "").strip()
    if env_mode:
        return env_mode
    host = (settings.host or "").strip()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "local-loopback"
    if Path("/.dockerenv").exists():
        return "container"
    return "local"


def _host_of(base_url: str) -> str | None:
    from urllib.parse import urlparse

    return urlparse(base_url).hostname


def _port_of(base_url: str) -> int | None:
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def local_hostname() -> str:
    """当前主机名（诊断展示用，非安全边界）。"""
    return socket.gethostname()
