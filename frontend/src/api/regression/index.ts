import { request } from "../client";
import type { components } from "../openapi.gen";

// 回归闭环 API 适配层 — 类型统一取自 OpenAPI 生成 schema，避免手写漂移。

export type RegressionCaseInfo = components["schemas"]["RegressionCaseResponse"];

export type RegressionCasePayload = components["schemas"]["RegressionCaseCreateRequest"];

export type RegressionRunInfo = components["schemas"]["RegressionRunResponse"];

export type RegressionRunItemInfo = components["schemas"]["RegressionRunItemResponse"];

export type RegressionRunSummaryInfo = components["schemas"]["RegressionRunSummaryResponse"];

export type RegressionRunDetailInfo = components["schemas"]["RegressionRunDetailResponse"];

// 差异明细内嵌在 summary.diff（dict[str, Any]）中，前端定义展示形状
export interface RegressionDiffEntryInfo {
  category?: string;
  fingerprint?: string;
  title?: string;
  severity?: string;
  findingType?: string;
  location?: string | null;
  caseId?: string | null;
  currentTaskId?: string | null;
  baselineTaskId?: string | null;
}

// ── 用例 ──

export function listRegressionCases(
  projectId: string,
  options: { signal?: AbortSignal } = {},
): Promise<components["schemas"]["RegressionCaseListResponse"]> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/regression-cases`,
    { signal: options.signal },
  );
}

export function createRegressionCase(
  projectId: string,
  payload: Partial<RegressionCasePayload>,
): Promise<RegressionCaseInfo> {
  return request(`/projects/${encodeURIComponent(projectId)}/regression-cases`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateRegressionCase(
  caseId: string,
  payload: Record<string, unknown>,
): Promise<RegressionCaseInfo> {
  return request(`/regression-cases/${encodeURIComponent(caseId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteRegressionCase(caseId: string): Promise<void> {
  return request(`/regression-cases/${encodeURIComponent(caseId)}`, { method: "DELETE" });
}

// ── 批次 ──

export function createRegressionRun(
  projectId: string,
): Promise<components["schemas"]["RegressionRunResponse"]> {
  return request(`/projects/${encodeURIComponent(projectId)}/regression-runs`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function listRegressionRuns(
  projectId: string,
  query: { offset?: number; limit?: number; status?: string } = {},
): Promise<components["schemas"]["RegressionRunListResponse"]> {
  const params = new URLSearchParams();
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.status) params.set("status", query.status);
  const qs = params.toString();
  return request(`/projects/${encodeURIComponent(projectId)}/regression-runs${qs ? `?${qs}` : ""}`);
}

export function getRegressionRun(
  runId: string,
  options: { signal?: AbortSignal } = {},
): Promise<RegressionRunDetailInfo> {
  return request(`/regression-runs/${encodeURIComponent(runId)}`, {
    signal: options.signal,
  });
}

export function cancelRegressionRun(runId: string): Promise<RegressionRunInfo> {
  return request(`/regression-runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ── 基线 ──

export function getRegressionBaseline(projectId: string): Promise<{
  baselineRunId: string | null;
}> {
  return request(`/projects/${encodeURIComponent(projectId)}/regression-baseline`);
}

export function setRegressionBaseline(
  projectId: string,
  runId: string,
): Promise<{ baselineRunId: string | null }> {
  return request(`/projects/${encodeURIComponent(projectId)}/regression-baseline`, {
    method: "PUT",
    body: JSON.stringify({ runId }),
  });
}
