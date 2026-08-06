import {request} from "../client";
import type {TaskPayload} from "../types";
import type {DashboardStats, LLMTraceRecord, ReportData, Task, TaskDisplayStatus, TaskListResponse, TaskStartResponse, TimelineEvent,} from "../../types";
import type { components } from "../openapi.gen";

export function listTasks(
    filters: {
        status?: TaskDisplayStatus | "";
        projectId?: string;
        taskType?: components["schemas"]["TaskType"] | "";
        q?: string;
        offset?: number;
        limit?: number;
    } = {},
): Promise<TaskListResponse> {
    const params = new URLSearchParams();
    if (filters.status && filters.status !== "queued") params.set("status", filters.status);
    if (filters.projectId) params.set("projectId", filters.projectId);
    if (filters.taskType) params.set("taskType", filters.taskType);
    if (filters.q) params.set("q", filters.q);
    if (filters.offset !== undefined) params.set("offset", String(filters.offset));
    if (filters.limit !== undefined) params.set("limit", String(filters.limit));
    const query = params.toString();
    return request<TaskListResponse>(`/tasks${query ? `?${query}` : ""}`);
}

export function getTask(taskId: string): Promise<Task> {
    return request<Task>(`/tasks/${encodeURIComponent(taskId)}`);
}

export function createTask(payload: TaskPayload): Promise<Task> {
    return request<Task>("/tasks", {method: "POST", body: JSON.stringify(payload)});
}

export function updateTask(taskId: string, payload: TaskPayload): Promise<Task> {
    return request<Task>(`/tasks/${encodeURIComponent(taskId)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
    });
}

export function deleteTask(taskId: string): Promise<void> {
    return request<void>(`/tasks/${encodeURIComponent(taskId)}`, {method: "DELETE"});
}

export function startTask(taskId: string): Promise<TaskStartResponse> {
    return request<TaskStartResponse>(`/tasks/${encodeURIComponent(taskId)}/start`, {
        method: "POST",
    });
}

export function restartTask(taskId: string): Promise<TaskStartResponse> {
    return request<TaskStartResponse>(`/tasks/${encodeURIComponent(taskId)}/restart`, {
        method: "POST",
    });
}

export function getTaskReportJson(taskId: string): Promise<ReportData> {
    return request<ReportData>(`/tasks/${encodeURIComponent(taskId)}/report.json`);
}

export function getTaskEvents(taskId: string): Promise<TimelineEvent[]> {
    return request<TimelineEvent[]>(`/tasks/${encodeURIComponent(taskId)}/events`);
}

export function getTaskTraces(taskId: string): Promise<LLMTraceRecord[]> {
    return request<LLMTraceRecord[]>(`/tasks/${encodeURIComponent(taskId)}/llm-traces`);
}

export function inferTaskLimits(goal: string, startUrl?: string): Promise<{maxSteps: number; timeoutSeconds: number}> {
    const params = new URLSearchParams({goal});
    if (startUrl) params.set("startUrl", startUrl);
    return request(`/tasks/infer-limits?${params.toString()}`);
}

export function getDashboardStats(recentLimit?: number): Promise<DashboardStats> {
    const query = recentLimit !== undefined ? `?recentLimit=${recentLimit}` : "";
    return request<DashboardStats>(`/tasks/stats${query}`);
}

// ── 白盒分析执行 ──────────────────────────────────────────

export type AnalysisRunSummary = components["schemas"]["AnalysisRunSummaryResponse"];

/** @deprecated Alias — use AnalysisRunSummary directly */
export type AnalysisRunListItem = AnalysisRunSummary;

export interface PageResponse<T> {
    items: T[];
    nextCursor?: string | null;
    total?: number | null;
    hasMore: boolean;
}

export type EndpointInfo = components["schemas"]["EndpointResponse"];

export type CallNodeInfo = components["schemas"]["CallNodeResponse"];

export type CallEdgeInfo = components["schemas"]["CallEdgeResponse"];

export type ExecutionFlowStepInfo = components["schemas"]["ExecutionFlowStepResponse"];

export type ExecutionFlowInfo = components["schemas"]["ExecutionFlowResponse"];

export type DiagnosticsInfo = components["schemas"]["DiagnosticsResponse"];

export function listAnalysisRuns(
    taskId: string, offset?: number, limit?: number,
): Promise<PageResponse<AnalysisRunListItem>> {
    const params = new URLSearchParams();
    if (offset !== undefined) params.set("offset", String(offset));
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<AnalysisRunListItem>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs${query ? `?${query}` : ""}`,
    );
}

export function getAnalysisRunSummary(
    taskId: string, analysisId: string,
): Promise<AnalysisRunSummary> {
    return request<AnalysisRunSummary>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}`,
    );
}

export function listAnalysisEndpoints(
    taskId: string, analysisId: string, cursor?: string | null, limit?: number,
): Promise<PageResponse<EndpointInfo>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<EndpointInfo>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/endpoints${query ? `?${query}` : ""}`,
    );
}

export function listAnalysisCallNodes(
    taskId: string, analysisId: string,
    className?: string | null, methodName?: string | null,
    cursor?: string | null, limit?: number,
): Promise<PageResponse<CallNodeInfo>> {
    const params = new URLSearchParams();
    if (className) params.set("className", className);
    if (methodName) params.set("methodName", methodName);
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<CallNodeInfo>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/call-nodes${query ? `?${query}` : ""}`,
    );
}

export function listAnalysisCallEdges(
    taskId: string, analysisId: string,
    entryNodeId?: string | null, cursor?: string | null, limit?: number,
): Promise<PageResponse<CallEdgeInfo>> {
    const params = new URLSearchParams();
    if (entryNodeId) params.set("entryNodeId", entryNodeId);
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<CallEdgeInfo>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/call-graph${query ? `?${query}` : ""}`,
    );
}

export function listAnalysisExecutionFlows(
    taskId: string, analysisId: string, cursor?: string | null, limit?: number,
): Promise<PageResponse<ExecutionFlowInfo>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<ExecutionFlowInfo>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/execution-flows${query ? `?${query}` : ""}`,
    );
}

export function getAnalysisDiagnostics(
    taskId: string, analysisId: string,
): Promise<DiagnosticsInfo> {
    return request<DiagnosticsInfo>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/diagnostics`,
    );
}

// ── 发现项 ──

export type FindingInfo = components["schemas"]["FindingDetailResponse"];

export function listAnalysisFindings(
    taskId: string,
    analysisId: string,
    cursor?: string | null,
    limit?: number,
): Promise<PageResponse<FindingInfo>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<FindingInfo>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/findings${query ? `?${query}` : ""}`,
    );
}

// ── 功能聚类 ──

export type ClusterInfo = components["schemas"]["ClusterResponse"];

export function listAnalysisClusters(
    taskId: string,
    analysisId: string,
    cursor?: string | null,
    limit?: number,
): Promise<PageResponse<ClusterInfo>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    return request<PageResponse<ClusterInfo>>(
        `/tasks/${encodeURIComponent(taskId)}/analysis-runs/${encodeURIComponent(analysisId)}/clusters${query ? `?${query}` : ""}`,
    );
}
