import { request } from "../client";

// ── 关联运行 ──

export interface CorrelationRunInfo {
  correlationRunId: string;
  projectId: string;
  blackboxRunId: string;
  desiredSourceSnapshotId: string;
  desiredAnalysisConfigDigest: string;
  requiredAnalyzerVersion: string;
  allowPartialAnalysis: boolean;
  analysisId: string | null;
  boundSourceSnapshotId: string | null;
  analysisProjectionVersion: number | null;
  correlationConfigDigest: string;
  matcherVersion: string;
  normalizationVersion: string;
  supersedesCorrelationRunId: string | null;
  sourceAlignmentStatus: string;
  status: string;
  activeAttemptId: string | null;
  sourceMismatchOverridden: boolean;
  sourceMismatchOverrideBy: string | null;
  sourceMismatchOverrideAt: string | null;
  sourceMismatchOverrideReason: string | null;
  startedAt: string | null;
  completedAt: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
}

export function getCorrelationRun(id: string): Promise<CorrelationRunInfo> {
  return request<CorrelationRunInfo>(`/correlation-runs/${encodeURIComponent(id)}`);
}

// ── 尝试 ──

export interface CorrelationAttemptInfo {
  correlationAttemptId: string;
  correlationRunId: string;
  attemptNumber: number;
  status: string;
  evidenceCompleteness: string;
  leaseOwner: string | null;
  startedAt: string;
  completedAt: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
}

export function listAttempts(runId: string): Promise<{ items: CorrelationAttemptInfo[]; total: number }> {
  return request<{ items: CorrelationAttemptInfo[]; total: number }>(
    `/correlation-runs/${encodeURIComponent(runId)}/attempts`,
  );
}

export function getAttempt(runId: string, attemptId: string): Promise<CorrelationAttemptInfo> {
  return request<CorrelationAttemptInfo>(
    `/correlation-runs/${encodeURIComponent(runId)}/attempts/${encodeURIComponent(attemptId)}`,
  );
}

// ── 汇总 ──

export interface CorrelationSummaryInfo {
  correlationRunId: string;
  status: string;
  sourceAlignmentStatus: string;
  capturedRequestCount: number;
  correlatableRequestCount: number;
  confirmedMatchedRequestCount: number;
  ambiguousRequestCount: number;
  methodMismatchCandidateCount: number;
  unmatchedRequestCount: number;
  totalEndpointCount: number;
  confirmedTouchedEndpointCount: number;
  candidateTouchedEndpointCount: number;
  uncoveredEndpointCount: number;
  attemptedEvidenceCount: number;
  totalFindingCount: number;
  confirmedRelatedFindingCount: number;
  candidateRelatedFindingCount: number;
  unrelatedFindingCount: number;
  crossOriginFilteredCount: number;
  resourceFilteredCount: number;
  droppedRequestCount: number;
  failedCaptureCount: number;
  evidenceCompleteness: string;
  matcherVersion: string;
  normalizationVersion: string;
}

export function getCorrelationSummary(runId: string): Promise<CorrelationSummaryInfo> {
  return request<CorrelationSummaryInfo>(
    `/correlation-runs/${encodeURIComponent(runId)}/summary`,
  );
}

// ── 端点证据 ──

export interface EndpointEvidenceCandidateInfo {
  endpointId: string;
  candidateRank: number;
  matchStrategy: string;
  confidence: string;
  reasonCode: string;
  selected: boolean;
}

export interface EndpointEvidenceInfo {
  endpointEvidenceId: string;
  correlationAttemptId: string;
  requestEvidenceId: string;
  resolutionStatus: string;
  matchStrategy: string;
  confidence: string;
  matchedEndpointId: string | null;
  matchedEndpointInfo: unknown | null;
  matchReasonCode: string;
  candidateCount: number;
  httpMethod: string | null;
  requestPath: string | null;
  displayPath: string | null;
  origin: string | null;
  resourceType: string | null;
  candidates: EndpointEvidenceCandidateInfo[];
  executionFlows: unknown[];
}

export interface EndpointEvidencePage {
  items: EndpointEvidenceInfo[];
  total: number | null;
  hasMore: boolean;
}

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

export interface HttpRequestEvidenceInfo {
  requestEvidenceId: string;
  blackboxRunId: string;
  taskId: string;
  stepExecutionId: string | null;
  stepAttempt: number;
  requestSequence: number;
  httpMethod: string;
  displayPath: string;
  origin: string;
  resourceType: string;
  endpointMatchEligibility: string;
  responseStatus: number | null;
  outcome: string;
  requestOwner: string;
  responseFromServiceWorker: boolean;
  pageSequence: number;
  capturedAt: string;
  finishedAt: string | null;
}

export interface HttpRequestEvidencePage {
  items: HttpRequestEvidenceInfo[];
  total: number | null;
  hasMore: boolean;
}

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

export interface FindingEvidenceInfo {
  findingEvidenceId: string;
  correlationAttemptId: string;
  findingId: string;
  findingInfo: unknown | null;
  bestRelationType: string;
  minimumCallDistance: number | null;
  confirmedRequestCount: number;
  candidateRequestCount: number;
}

export interface FindingEvidencePage {
  items: FindingEvidenceInfo[];
  total: number | null;
  hasMore: boolean;
}

export function listFindingEvidence(
  runId: string,
  offset = 0,
  limit = 100,
): Promise<FindingEvidencePage> {
  return request<FindingEvidencePage>(
    `/correlation-runs/${encodeURIComponent(runId)}/finding-evidence?offset=${offset}&limit=${limit}`,
  );
}

// ── 采集质量 ──

export interface CaptureQualityInfo {
  blackboxRunId: string;
  totalObserved: number;
  acceptedStarted: number;
  persistedCount: number;
  filteredByResourceType: number;
  filteredCrossOrigin: number;
  filteredByMethod: number;
  filteredWebsocketCount: number;
  filteredPathTooLong: number;
  droppedPendingLimit: number;
  droppedRunLimit: number;
  droppedWriterQueueLimit: number;
  writerRetryCount: number;
  writerFailedBatchCount: number;
  persistenceFailed: number;
  truncated: boolean;
  truncationReason: string | null;
}

export function getCaptureQuality(runId: string): Promise<CaptureQualityInfo> {
  return request<CaptureQualityInfo>(
    `/correlation-runs/${encodeURIComponent(runId)}/capture-quality`,
  );
}

// ── 操作 ──

export function bindAnalysis(
  runId: string,
  analysisId: string,
  expectedProjectionVersion?: number,
  sourceMismatchOverride = false,
  sourceMismatchOverrideReason?: string,
): Promise<void> {
  return request<void>(
    `/correlation-runs/${encodeURIComponent(runId)}/bind-analysis`,
    {
      method: "POST",
      body: JSON.stringify({
        analysisId,
        expectedProjectionVersion: expectedProjectionVersion ?? null,
        sourceMismatchOverride,
        sourceMismatchOverrideReason: sourceMismatchOverrideReason ?? null,
      }),
    },
  );
}

// ── 任务级查询 ──

export function listCorrelationRunsByTask(
  taskId: string,
): Promise<CorrelationRunInfo[]> {
  return request<CorrelationRunInfo[]>(
    `/correlation-runs?taskId=${encodeURIComponent(taskId)}`,
  );
}
