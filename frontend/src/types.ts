export type TaskStatus =
    | "pending"
    | "running"
    | "paused"
    | "completed"
    | "failed"
    | "cancelled"
    | "timeout";

export type SchedulerStatus = "queued" | "running";

export type TaskDisplayStatus = TaskStatus | SchedulerStatus;

export type TaskType = "blackbox" | "whitebox";

export type StepResult = "success" | "failed" | "skipped";

export type FindingSeverity = "info" | "low" | "medium" | "high" | "critical";

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

export interface ConfigSummary {
    serverHost: string;
    serverPort: number;
    corsAllowOrigins: string[];
    schedulerConcurrency: number;
    schedulerQueueMaxSize: number;
    schedulerShutdownTimeoutSeconds: number;
    eventsHistoryLimit: number;
    eventsSubscriberQueueSize: number;
    modelConfigsCount: number;
    defaultModelConfigId: string | null;
}

export interface Project {
    projectId: string;
    name: string;
    description: string | null;
    baseUrl: string | null;
    gitUrl: string | null;
    authStateName: string | null;
    defaultMaxSteps: number | null;
    defaultTimeoutSeconds: number | null;
    defaultCaptureScreenshots: boolean;
    parameters: Record<string, unknown>;
    createdAt: string;
    updatedAt: string;
}

export interface ProjectListResponse {
    total: number;
    projects: Project[];
}

export interface TaskLog {
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

export interface Finding {
    findingId: string;
    title: string;
    description: string;
    severity: FindingSeverity;
    findingType: string;
    url: string | null;
    location: string | null;
    screenshotPath: string | null;
    createdAt: string;
}

export interface Task {
    taskId: string;
    projectId: string | null;
    goal: string;
    name: string | null;
    startUrl: string | null;
    taskType: TaskType;
    status: TaskStatus;
    schedulerStatus: SchedulerStatus | null;
    maxSteps: number;
    timeoutSeconds: number;
    captureScreenshots: boolean;
    currentStep: number;
    findingCount?: number;
    parameters: Record<string, unknown>;
    logs?: TaskLog[];
    findings?: Finding[];
    createdAt: string;
    startedAt: string | null;
    completedAt: string | null;
    reportPath: string | null;
    resultSummary: string | null;
    errorMessage: string | null;
}

export interface TaskListResponse {
    total: number;
    tasks: Task[];
}

export interface TaskStartResponse {
    schedulerStatus: SchedulerStatus;
    task: Task;
}

export interface ModelConfig {
    modelConfigId: string;
    name: string;
    provider: string;
    model: string;
    apiKeySet: boolean;
    baseUrl: string;
    completionsPath: string;
    maxRetries: number;
    timeoutSeconds: number;
    taskType: TaskType | null;
    isDefault: boolean;
    enabled: boolean;
    createdAt: string;
    updatedAt: string;
}

export interface ModelConfigListResponse {
    total: number;
    models: ModelConfig[];
}

export interface ModelConnectionTestResponse {
    success: boolean;
    message: string;
    model: string | null;
    latencyMs: number | null;
}

export interface TaskEvent<T = Record<string, unknown>> {
    sequence?: number;
    type?: string;
    eventType?: string;
    taskId?: string;
    data?: T;
    createdAt?: string;
}

export interface DashboardStats {
    tasksTotal: number;
    runningTotal: number;
    findingsTotal: number;
    recentTasks: Task[];
}

export interface ReportFinding {
    finding_id: string;
    title: string;
    description: string;
    severity: FindingSeverity;
    finding_type: string;
    url: string | null;
    location: string | null;
    screenshot_path: string | null;
    created_at: string;
}

export interface ReportTaskLog {
    step_number: number;
    action: string;
    result: StepResult;
    task_log_id: string;
    params: Record<string, unknown>;
    url_before: string | null;
    url_after: string | null;
    screenshot_path: string | null;
    message: string | null;
    error: string | null;
    error_code: string | null;
    created_at: string;
}

export interface ReportTask {
    task_id: string;
    project_id: string | null;
    goal: string;
    start_url: string | null;
    task_type: TaskType;
    status: TaskStatus;
    max_steps: number;
    timeout_seconds: number;
    capture_screenshots: boolean;
    current_step: number;
    parameters: Record<string, unknown>;
    logs: ReportTaskLog[];
    findings: ReportFinding[];
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    report_path: string | null;
    result_summary: string | null;
    error_message: string | null;
}

export interface ReportData {
    task: ReportTask;
    report_id: string;
    title: string;
    summary: string;
    generated_at: string;
    steps: ReportTaskLog[];
    findings: ReportFinding[];
    display_steps: ReportTaskLog[];
    total_steps_count: number;
    hidden_steps_count: number;
}
