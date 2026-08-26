"""诊断中心服务状态聚合（docs/optimizations/diagnostics-center-plan.md 第 7 章）。

MVP 覆盖：Python 进程、Java 分析器（actuator 探测，带 TTL 缓存）、SQLite、
Web 静态资源、日志目录占用。同步方法由路由层经 ``run_in_thread`` 执行；
``java_status`` 是唯一异步方法（httpx 探测）。
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from argus_py.config.server_settings import ServerSettings
from argus_py.core.paths import API_STATIC_DIR
from argus_py.observability.diagnostics_store import FileDiagnosticsLogStore

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
    """聚合各组件健康状态与日志目录用量。"""

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
                timeout=min(3.0, max(0.5, self._settings.java_analyzer_request_timeout))
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
