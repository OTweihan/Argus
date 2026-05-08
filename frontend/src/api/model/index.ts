import {request} from "../client";
import type {ModelConfigPayload, ModelConnectionPayload} from "../types";
import type {
    ModelConfig,
    ModelConfigListResponse,
    ModelConnectionTestResponse,
} from "../../types";

export function listModels(includeDisabled = true): Promise<ModelConfigListResponse> {
    return request<ModelConfigListResponse>(
        `/config/models?includeDisabled=${includeDisabled}`,
    );
}

export function createModel(payload: ModelConfigPayload): Promise<ModelConfig> {
    return request<ModelConfig>("/config/models", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export function updateModel(
    modelConfigId: string,
    payload: Partial<ModelConfigPayload>,
): Promise<ModelConfig> {
    return request<ModelConfig>(`/config/models/${encodeURIComponent(modelConfigId)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
    });
}

export function deleteModel(modelConfigId: string): Promise<void> {
    return request<void>(`/config/models/${encodeURIComponent(modelConfigId)}`, {
        method: "DELETE",
    });
}

export function testModel(payload: ModelConnectionPayload): Promise<ModelConnectionTestResponse> {
    return request<ModelConnectionTestResponse>("/config/models/test", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}
