import {request} from "../client";
import type {PromptPreviewPayload, PromptPreviewResponse} from "../types";

export function previewPrompt(payload: PromptPreviewPayload): Promise<PromptPreviewResponse> {
    return request<PromptPreviewResponse>("/prompts/preview", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}
