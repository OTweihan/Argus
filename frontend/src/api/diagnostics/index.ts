import { request } from "../client";
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
