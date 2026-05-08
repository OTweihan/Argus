import {request, ApiError, reportUrl} from "../client";
import type {TaskPayload} from "../types";
import type {
    ReportData,
    Task,
    TaskDisplayStatus,
    TaskListResponse,
    TaskStartResponse,
} from "../../types";

export function listTasks(
    filters: {
        status?: TaskDisplayStatus | "";
        projectId?: string;
        offset?: number;
        limit?: number;
    } = {},
): Promise<TaskListResponse> {
    const params = new URLSearchParams();
    if (filters.status && filters.status !== "queued") params.set("status", filters.status);
    if (filters.projectId) params.set("projectId", filters.projectId);
    if (filters.offset) params.set("offset", String(filters.offset));
    if (filters.limit) params.set("limit", String(filters.limit));
    const query = params.toString();
    return request<TaskListResponse>(`/tasks${query ? `?${query}` : ""}`);
}

export function getTask(taskId: string): Promise<Task> {
    return request<Task>(`/tasks/${encodeURIComponent(taskId)}`);
}

export function createTask(payload: TaskPayload): Promise<Task> {
    return request<Task>("/tasks", {method: "POST", body: JSON.stringify(payload)});
}

export function startTask(taskId: string): Promise<TaskStartResponse> {
    return request<TaskStartResponse>(`/tasks/${encodeURIComponent(taskId)}/start`, {
        method: "POST",
    });
}

export async function getTaskReportHtml(taskId: string): Promise<string> {
    const response = await fetch(reportUrl(taskId));
    if (!response.ok) throw new ApiError(`获取报告失败：HTTP ${response.status}`, response.status);
    return response.text();
}

export function getTaskReportJson(taskId: string): Promise<ReportData> {
    return request<ReportData>(reportUrl(taskId, true));
}
