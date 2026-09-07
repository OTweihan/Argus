import { request, requestBlob, requestBlobPost } from "../client";
import type { components } from "../openapi.gen";

export type DiagnosticsLogEntry = components["schemas"]["DiagnosticsLogEntry"];
export type DiagnosticsLogDetail = components["schemas"]["DiagnosticsLogDetail"];
export type DiagnosticsLogPage = components["schemas"]["DiagnosticsLogPage"];
export type DiagnosticsContextResponse = components["schemas"]["DiagnosticsContextResponse"];
export type DiagnosticsTraceResponse = components["schemas"]["DiagnosticsTraceResponse"];
export type DiagnosticsServicesResponse = components["schemas"]["DiagnosticsServicesResponse"];
export type ServiceStatus = components["schemas"]["ServiceStatusResponse"];
export type LogsUsage = components["schemas"]["LogsUsageResponse"];
export type RunsListResponse = components["schemas"]["RunsListResponse"];
export type RunSummary = components["schemas"]["RunSummaryResponse"];
export type DiagnosticsOverviewResponse = components["schemas"]["DiagnosticsOverviewResponse"];
export type DiagnosticsSystemInfoResponse = components["schemas"]["DiagnosticsSystemInfoResponse"];
export type DiagnosticsEventsPage = components["schemas"]["DiagnosticsEventsPage"];
export type FrontendEventResponse = components["schemas"]["FrontendEventResponse"];
export type DiagnosticsBundleResponse = components["schemas"]["DiagnosticsBundleResponse"];

/** 日志检索过滤条件（wire 参数 camelCase，与 OpenAPI 契约一致）。 */
export interface DiagnosticsLogsFilters {
  component?: string;
  level?: string;
  keyword?: string;
  requestId?: string;
  runId?: string;
  /** ISO 8601 时间下界（含）。 */
  from?: string;
  /** ISO 8601 时间上界（含）。 */
  to?: string;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function searchDiagnosticsLogs(
  filters: DiagnosticsLogsFilters & { limit?: number; cursor?: string } = {},
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsLogPage> {
  const query = buildQuery({
    component: filters.component,
    level: filters.level,
    keyword: filters.keyword,
    requestId: filters.requestId,
    runId: filters.runId,
    from: filters.from,
    to: filters.to,
    limit: filters.limit,
    cursor: filters.cursor,
  });
  return request<DiagnosticsLogPage>(`/diagnostics/logs${query}`, { signal: options.signal });
}

export function getDiagnosticsLogDetail(
  eventId: string,
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsLogDetail> {
  return request<DiagnosticsLogDetail>(
    `/diagnostics/logs/${encodeURIComponent(eventId)}`,
    options,
  );
}

export function getDiagnosticsLogContext(
  eventId: string,
  before = 20,
  after = 20,
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsContextResponse> {
  return request<DiagnosticsContextResponse>(
    `/diagnostics/logs/${encodeURIComponent(eventId)}/context${buildQuery({ before, after })}`,
    options,
  );
}

export function traceDiagnosticsRequest(
  requestId: string,
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsTraceResponse> {
  return request<DiagnosticsTraceResponse>(
    `/diagnostics/requests/${encodeURIComponent(requestId)}`,
    options,
  );
}

export function getDiagnosticsServices(
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsServicesResponse> {
  return request<DiagnosticsServicesResponse>(`/diagnostics/services`, options);
}

export function listDiagnosticsRuns(
  limit = 50,
  options: { signal?: AbortSignal } = {},
): Promise<RunsListResponse> {
  return request<RunsListResponse>(`/diagnostics/runs${buildQuery({ limit })}`, options);
}

export function getDiagnosticsRun(
  runId: string,
  options: { signal?: AbortSignal } = {},
): Promise<RunSummary> {
  return request<RunSummary>(`/diagnostics/runs/${encodeURIComponent(runId)}`, options);
}

export function searchDiagnosticsRunLogs(
  runId: string,
  filters: DiagnosticsLogsFilters & { limit?: number; cursor?: string } = {},
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsLogPage> {
  const query = buildQuery({
    component: filters.component,
    level: filters.level,
    keyword: filters.keyword,
    requestId: filters.requestId,
    from: filters.from,
    to: filters.to,
    limit: filters.limit,
    cursor: filters.cursor,
  });
  return request<DiagnosticsLogPage>(
    `/diagnostics/runs/${encodeURIComponent(runId)}/logs${query}`,
    options,
  );
}

export function getDiagnosticsOverview(
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsOverviewResponse> {
  return request<DiagnosticsOverviewResponse>(`/diagnostics/overview`, options);
}

export function getDiagnosticsSystem(
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsSystemInfoResponse> {
  return request<DiagnosticsSystemInfoResponse>(`/diagnostics/system`, options);
}

export function listDiagnosticsEvents(
  params: { limit?: number; cursor?: string; level?: string; keyword?: string } = {},
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsEventsPage> {
  const query = buildQuery({
    limit: params.limit,
    cursor: params.cursor,
    level: params.level,
    keyword: params.keyword,
  });
  return request<DiagnosticsEventsPage>(`/diagnostics/events${query}`, options);
}

export interface FrontendEventPayload {
  message: string;
  level?: string;
  timestamp?: string;
  errorType?: string;
  errorStack?: string;
  url?: string;
  userAgent?: string;
  module?: string;
  requestId?: string;
  page?: string;
}

export function postFrontendEvent(
  body: FrontendEventPayload,
  options: { signal?: AbortSignal } = {},
): Promise<FrontendEventResponse> {
  return request<FrontendEventResponse>(`/diagnostics/frontend-events`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
  });
}

/** 日志导出过滤条件（与 OpenAPI DiagnosticsExportRequest 对齐）。 */
export interface DiagnosticsExportPayload {
  from?: string;
  to?: string;
  components?: string[];
  levels?: string[];
  keyword?: string;
  requestId?: string;
  runId?: string;
  maxEvents?: number;
}

export interface DiagnosticsBundlePayload extends DiagnosticsExportPayload {
  includeSystemInfo?: boolean;
  includeRecentEvents?: boolean;
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

/** 导出日志片段 zip 并触发浏览器下载。 */
export async function exportDiagnosticsLogs(
  body: DiagnosticsExportPayload = {},
  options: { signal?: AbortSignal; filename?: string } = {},
): Promise<{ eventCount: number; truncated: boolean; scanLimited: boolean }> {
  const { blob, headers } = await requestBlobPost(`/diagnostics/export`, body, options.signal);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  triggerBlobDownload(blob, options.filename ?? `argus-diagnostics-export-${stamp}.zip`);
  return {
    eventCount: Number(headers.get("x-argus-export-event-count") ?? "0"),
    truncated: headers.get("x-argus-export-truncated") === "1",
    scanLimited: headers.get("x-argus-export-scan-limited") === "1",
  };
}

/** 创建诊断包并立即下载 zip。 */
export async function createAndDownloadDiagnosticsBundle(
  body: DiagnosticsBundlePayload = {},
  options: { signal?: AbortSignal } = {},
): Promise<DiagnosticsBundleResponse> {
  const meta = await request<DiagnosticsBundleResponse>(`/diagnostics/bundles`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
  });
  const bundleId = meta.bundleId;
  // downloadPath 为相对 API 前缀路径；统一用 bundleId 拼装。
  const blob = await requestBlob(
    `/diagnostics/bundles/${encodeURIComponent(bundleId)}`,
    options.signal,
  );
  triggerBlobDownload(blob, `argus-diagnostics-bundle-${bundleId}.zip`);
  return meta;
}
