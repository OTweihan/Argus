
/* ----- 以下类型从 OpenAPI schema 自动生成，由 FastAPI Pydantic 模型驱动 ---- */

import type {components} from "./api/openapi.gen";

/** @description 任务状态 */
export type TaskStatus = components["schemas"]["TaskStatus"];

/** @description 任务类型 */
export type TaskType = components["schemas"]["TaskType"];

/** @description 步骤执行结果 */
export type StepResult = components["schemas"]["StepResult"];

/** @description 问题严重级别 */
export type FindingSeverity = components["schemas"]["FindingSeverity"];

/** @description 问题分类 */
export type FindingType = components["schemas"]["FindingType"];

/** @description 任务详情响应（含可选 logs/findings，兼容 summary） */
export type Task = Omit<components["schemas"]["TaskResponse"], "logs" | "findings"> & {
    logs?: components["schemas"]["TaskLogResponse"][];
    findings?: components["schemas"]["FindingResponse"][];
    findingCount?: number;
};

/** @description 任务步骤日志响应 */
export type TaskLog = components["schemas"]["TaskLogResponse"];

/** @description 问题记录响应 */
export type Finding = components["schemas"]["FindingResponse"];

/** @description 轻量任务列表响应 */
export type TaskListResponse = components["schemas"]["TaskSummaryListResponse"];

/** @description 任务启动响应 */
export type TaskStartResponse = components["schemas"]["TaskStartResponse"];

/** @description 仪表盘聚合统计 */
export type DashboardStats = components["schemas"]["DashboardStatsResponse"];

/** @description 项目响应 */
export type Project = components["schemas"]["ProjectResponse"];

/** @description 项目列表响应 */
export type ProjectListResponse = components["schemas"]["ProjectListResponse"];

/** @description 模型配置响应 */
export type ModelConfig = components["schemas"]["ModelConfigResponse"];

/** @description 模型配置列表响应 */
export type ModelConfigListResponse = components["schemas"]["ModelConfigListResponse"];

/** @description 模型连接检查响应 */
export type ModelConnectionTestResponse =
    components["schemas"]["ModelConnectionTestResponse"];

/** @description 配置摘要 */
export type ConfigSummary = components["schemas"]["ConfigSummaryResponse"];

/* ----- 以下类型非 OpenAPI schema，保持手写 ----- */

export type SchedulerStatus = "queued" | "running";

export type TaskDisplayStatus = TaskStatus | SchedulerStatus;

export interface TimelineEvent {
    eventId: string;
    taskId: string;
    eventType: string;
    phase: string;
    stepNumber: number;
    summary: string;
    data: Record<string, unknown>;
    createdAt: string;
}

export interface LLMTraceRecord {
    traceId: string;
    taskId: string;
    phase: string;
    event: string;
    systemPrompt?: string;
    inputPayload?: Record<string, unknown>;
    model: string;
    baseUrlHost?: string;
    latencyMs?: number;
    tokenUsage?: Record<string, number>;
    rawResponse?: string;
    parsedResult?: unknown;
    parseError?: string;
    error?: string;
    timestamp: string;
}

export interface TaskEvent<T = Record<string, unknown>> {
    sequence?: number;
    eventType: string;
    taskId?: string;
    data: T;
    createdAt?: string;
}

// ── 报告类型（来自 report.json 而非 OpenAPI）─────────────────────────────────

export interface ReportFinding {
    findingId: string;
    title: string;
    description: string;
    severity: FindingSeverity;
    findingType: FindingType;
    url: string | null;
    location: string | null;
    screenshotPath: string | null;
    createdAt: string;
}

export interface ReportTaskLog {
    stepNumber: number;
    action: string;
    result: StepResult;
    taskLogId: string;
    params: Record<string, unknown>;
    urlBefore: string | null;
    urlAfter: string | null;
    screenshotPath: string | null;
    message: string | null;
    error: string | null;
    errorCode: string | null;
    createdAt: string;
}

export interface ReportTask {
    taskId: string;
    projectId: string | null;
    goal: string;
    startUrl: string | null;
    taskType: TaskType;
    status: TaskStatus;
    maxSteps: number;
    timeoutSeconds: number;
    captureScreenshots: boolean;
    currentStep: number;
    parameters: Record<string, unknown>;
    logs: ReportTaskLog[];
    findings: ReportFinding[];
    createdAt: string;
    startedAt: string | null;
    completedAt: string | null;
    reportPath: string | null;
    resultSummary: string | null;
    errorMessage: string | null;
}

export interface ReportData {
    task: ReportTask;
    reportId: string;
    title: string;
    summary: string;
    generatedAt: string;
    steps: ReportTaskLog[];
    findings: ReportFinding[];
    displaySteps: ReportTaskLog[];
    totalStepsCount: number;
    hiddenStepsCount: number;
}
