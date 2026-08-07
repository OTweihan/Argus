import { request } from "../client";
import type { components } from "../openapi.gen";

// ── 关联运行 ──

// 关联运行/尝试/汇总/证据等类型统一取自 OpenAPI 生成 schema，
// 避免手写接口与后端契约漂移（此前 sourceLocation: unknown 等字段即为漂移迹象）。

export type CorrelationRunInfo = components["schemas"]["CorrelationRunResponse"];

// ── 汇总 ──

export type CorrelationSummaryInfo = components["schemas"]["CorrelationSummaryResponse"];

export function getCorrelationSummary(runId: string): Promise<CorrelationSummaryInfo> {
  return request<CorrelationSummaryInfo>(`/correlation-runs/${encodeURIComponent(runId)}/summary`);
}

// ── 端点证据 ──

export type EndpointEvidenceCandidateInfo = components["schemas"]["EndpointEvidenceCandidateResponse"];

export type EndpointEvidenceInfo = components["schemas"]["EndpointEvidenceResponse"];

export type EndpointEvidencePage = components["schemas"]["EndpointEvidencePageResponse"];

export function listEndpointEvidence(
  runId: string,
  filters: {
    resolutionStatus?: string;
    matchStrategy?: string;
    offset?: number;
    limit?: number;
  } = {},
): Promise<EndpointEvidencePage> {
  const params = new URLSearchParams();
  if (filters.resolutionStatus) params.set("resolutionStatus", filters.resolutionStatus);
  if (filters.matchStrategy) params.set("matchStrategy", filters.matchStrategy);
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const query = params.toString();
  return request<EndpointEvidencePage>(
    `/correlation-runs/${encodeURIComponent(runId)}/endpoint-evidence${query ? `?${query}` : ""}`,
  );
}

// ── HTTP 请求证据 ──

export type HttpRequestEvidenceInfo = components["schemas"]["HttpRequestEvidenceResponse"];

export type HttpRequestEvidencePage = components["schemas"]["HttpRequestEvidencePageResponse"];

export function listUnmatchedRequests(
  runId: string,
  offset = 0,
  limit = 100,
): Promise<HttpRequestEvidencePage> {
  return request<HttpRequestEvidencePage>(
    `/correlation-runs/${encodeURIComponent(runId)}/unmatched-requests?offset=${offset}&limit=${limit}`,
  );
}

// ── Finding 关联 ──

export type FindingEvidenceInfo = components["schemas"]["FindingEvidenceResponse"];

export type FindingEvidencePage = components["schemas"]["FindingEvidencePageResponse"];

export function listFindingEvidence(
  runId: string,
  offset = 0,
  limit = 100,
): Promise<FindingEvidencePage> {
  return request<FindingEvidencePage>(
    `/correlation-runs/${encodeURIComponent(runId)}/finding-evidence?offset=${offset}&limit=${limit}`,
  );
}

// ── 未触达端点 ──
// 未触达端点列表返回的即白盒 EndpointResponse 结构，直接复用生成类型。

export type UncoveredEndpointInfo = components["schemas"]["EndpointResponse"];

export function listUncoveredEndpoints(
  runId: string,
  offset = 0,
  limit = 100,
): Promise<{ items: UncoveredEndpointInfo[]; total: number; hasMore: boolean }> {
  return request<{ items: UncoveredEndpointInfo[]; total: number; hasMore: boolean }>(
    `/correlation-runs/${encodeURIComponent(runId)}/uncovered-endpoints?offset=${offset}&limit=${limit}`,
  );
}

// ── 采集质量 ──

export type CaptureQualityInfo = components["schemas"]["CaptureQualityResponse"];

export function getCaptureQuality(runId: string): Promise<CaptureQualityInfo> {
  return request<CaptureQualityInfo>(
    `/correlation-runs/${encodeURIComponent(runId)}/capture-quality`,
  );
}

// ── 任务级查询 ──

export function listCorrelationRunsByTask(taskId: string): Promise<CorrelationRunInfo[]> {
  return request<CorrelationRunInfo[]>(`/correlation-runs?taskId=${encodeURIComponent(taskId)}`);
}
