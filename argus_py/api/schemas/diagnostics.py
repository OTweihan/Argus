"""诊断中心 API Schema（docs/optimizations/diagnostics-center-plan.md 第 17 章）。

wire 命名统一 camelCase（方案 1.3 字段命名约定），与既有路由惯例一致。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from argus_py.api.schemas.base import ApiModel


class DiagnosticsLogEntry(ApiModel):
    """统一诊断日志条目（列表/上下文/追踪共用）。"""

    event_id: str = Field(alias="eventId")
    timestamp: str
    level: str
    component: str
    module: str
    message: str
    request_id: str | None = Field(default=None, alias="requestId")
    run_id: str | None = Field(default=None, alias="runId")
    exception: str | None = None


class DiagnosticsLogSource(ApiModel):
    """日志来源定位（文件相对路径 + 行号）。"""

    file_path: str = Field(alias="filePath")
    line_number: int = Field(alias="lineNumber")


class DiagnosticsLogDetail(DiagnosticsLogEntry):
    """单条日志详情：完整消息、原始 JSON 与文件来源（方案 8.4）。"""

    raw: dict[str, Any] = Field(default_factory=dict)
    source: DiagnosticsLogSource


class DiagnosticsLogPage(ApiModel):
    """游标分页结果（方案 8.6）。"""

    items: list[DiagnosticsLogEntry] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")
    scan_limited: bool = Field(default=False, alias="scanLimited")


class DiagnosticsContextResponse(ApiModel):
    """日志前后上下文（方案 17.5）。"""

    items: list[DiagnosticsLogEntry] = Field(default_factory=list)


class DiagnosticsTraceResponse(ApiModel):
    """Request ID 追踪时间线（按时间正序，方案 9.3）。"""

    request_id: str = Field(alias="requestId")
    items: list[DiagnosticsLogEntry] = Field(default_factory=list)


class ServiceStatusResponse(ApiModel):
    """组件服务状态（方案 7.2）。"""

    name: str
    status: str
    version: str | None = None
    pid: int | None = None
    port: int | None = None
    host: str | None = None
    started_at: str | None = Field(default=None, alias="startedAt")
    uptime_seconds: float | None = Field(default=None, alias="uptimeSeconds")
    latency_ms: float | None = Field(default=None, alias="latencyMs")
    detail: str | None = None


class LogsUsageResponse(ApiModel):
    """日志目录空间占用。"""

    path: str
    total_bytes: int = Field(alias="totalBytes")
    file_count: int = Field(alias="fileCount")
    free_bytes: int | None = Field(default=None, alias="freeBytes")


class DiagnosticsServicesResponse(ApiModel):
    """服务状态聚合响应（方案 17.2）。"""

    services: list[ServiceStatusResponse] = Field(default_factory=list)
    logs_usage: LogsUsageResponse | None = Field(default=None, alias="logsUsage")
    checked_at: str = Field(alias="checkedAt")


class RunFileInfoResponse(ApiModel):
    """启动会话内单个日志文件信息。"""

    name: str
    size_bytes: int = Field(alias="sizeBytes")
    modified_at: str = Field(alias="modifiedAt")


class RunSummaryResponse(ApiModel):
    """启动会话摘要（方案 10.3 的 MVP 子集）。"""

    run_id: str = Field(alias="runId")
    started_at: str = Field(alias="startedAt")
    files: list[RunFileInfoResponse] = Field(default_factory=list)
    total_bytes: int = Field(alias="totalBytes")


class RunsListResponse(ApiModel):
    """启动会话列表（新会话在前）。"""

    runs: list[RunSummaryResponse] = Field(default_factory=list)
