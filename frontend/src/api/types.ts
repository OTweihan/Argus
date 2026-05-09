import type {ModelProvider, TaskType} from "../types";

export interface ProjectPayload {
    name: string;
    description?: string | null;
    baseUrl?: string | null;
    gitUrl?: string | null;
    authStateName?: string | null;
    defaultMaxSteps?: number | null;
    defaultTimeoutSeconds?: number | null;
    defaultCaptureScreenshots?: boolean;
    parameters?: Record<string, unknown>;
}

export interface TaskPayload {
    goal: string;
    name?: string | null;
    projectId: string;
    startUrl?: string | null;
    taskType?: TaskType;
    maxSteps?: number | null;
    timeoutSeconds?: number | null;
    captureScreenshots?: boolean | null;
    modelConfigId?: string | null;
    parameters?: Record<string, unknown>;
}

export interface ModelConfigPayload {
    name: string;
    provider: ModelProvider;
    model: string;
    apiKey?: string;
    baseUrl?: string | null;
    completionsPath?: string | null;
    maxTokens?: number | null;
    temperature?: number | null;
    maxRetries?: number | null;
    timeoutSeconds?: number | null;
    taskType?: TaskType | null;
    isDefault?: boolean;
    enabled?: boolean;
}

export interface ModelConnectionPayload extends Partial<ModelConfigPayload> {
    modelConfigId?: string | null;
}
