import {request} from "../client";
import type {ProjectPayload} from "../types";
import type {Project, ProjectListResponse} from "../../types";

export function listProjects(): Promise<ProjectListResponse> {
    return request<ProjectListResponse>("/projects");
}

export function createProject(payload: ProjectPayload): Promise<Project> {
    return request<Project>("/projects", {method: "POST", body: JSON.stringify(payload)});
}

export function updateProject(
    projectId: string,
    payload: Partial<ProjectPayload>,
): Promise<Project> {
    return request<Project>(`/projects/${encodeURIComponent(projectId)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
    });
}

export function deleteProject(projectId: string): Promise<void> {
    return request<void>(`/projects/${encodeURIComponent(projectId)}`, {method: "DELETE"});
}
