import {request} from "../client";
import type {TaskPayload} from "../types";
import type {ReportData, Task, TaskDisplayStatus, TaskListResponse, TaskStartResponse,} from "../../types";

export function listTasks(
    filters: {
        status?: TaskDisplayStatus | "";
        projectId?: string;
        q?: string;
        offset?: number;
        limit?: number;
    } = {},
): Promise<TaskListResponse> {
    const params = new URLSearchParams();
    if (filters.status && filters.status !== "queued") params.set("status", filters.status);
    if (filters.projectId) params.set("projectId", filters.projectId);
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

export function inferTaskLimits(goal: string, startUrl?: string): Promise<{maxSteps: number; timeoutSeconds: number}> {
    const params = new URLSearchParams({goal});
    if (startUrl) params.set("startUrl", startUrl);
    return request(`/tasks/infer-limits?${params.toString()}`);
}
