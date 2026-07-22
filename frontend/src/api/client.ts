import { getApiToken, requireApiToken } from "../auth";

export const API_BASE = (import.meta.env.VITE_ARGUS_API_BASE ?? "/argus/api").replace(/\/$/, "");
const DEFAULT_REQUEST_TIMEOUT_MS = Number(
    import.meta.env.VITE_ARGUS_API_TIMEOUT_MS ?? 180000,
);
const REQUEST_TIMEOUT_MS =
    Number.isFinite(DEFAULT_REQUEST_TIMEOUT_MS) && DEFAULT_REQUEST_TIMEOUT_MS > 0
        ? DEFAULT_REQUEST_TIMEOUT_MS
        : 180000;

export class ApiError extends Error {
    constructor(
        message: string,
        public readonly status: number,
        public readonly code = "HTTP_ERROR",
        public readonly details: Record<string, unknown> = {},
    ) {
        super(message);
    }
}

interface ApiErrorBody {
    error?: { code?: string; message?: string; details?: Record<string, unknown> };
    detail?: string | { code?: string; message?: string; details?: Record<string, unknown> };
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function apiErrorFromBody(body: unknown, status: number): ApiError | null {
    if (!isRecord(body)) {
        return null;
    }

    const error = isRecord(body.error) ? body.error : undefined;
    const detail = isRecord(body.detail) ? body.detail : undefined;
    const message =
        typeof error?.message === "string"
            ? error.message
            : typeof detail?.message === "string"
              ? detail.message
              : typeof body.detail === "string"
                ? body.detail
                : undefined;
    const code =
        typeof error?.code === "string"
            ? error.code
            : typeof detail?.code === "string"
              ? detail.code
              : "HTTP_ERROR";
    const details = isRecord(error?.details)
        ? error.details
        : isRecord(detail?.details)
          ? detail.details
          : {};

    return new ApiError(message ?? `请求失败：HTTP ${status}`, status, code, details);
}

async function parseResponseBody<T>(
    response: Response,
    contentType: string,
): Promise<T | ApiErrorBody | string> {
    if (!contentType.includes("application/json")) {
        return response.text();
    }
    const text = await response.text();
    if (!text) {
        return undefined as T;
    }
    try {
        return JSON.parse(text) as T | ApiErrorBody;
    } catch {
        throw new ApiError(
            `服务返回了无效 JSON：HTTP ${response.status}`,
            response.status,
            "INVALID_JSON_RESPONSE",
        );
    }
}

function createRequestSignal(signal?: AbortSignal): {
    signal: AbortSignal;
    cleanup: () => void;
    timedOut: () => boolean;
} {
    const controller = new AbortController();
    let timeoutReached = false;
    const timeoutId = window.setTimeout(() => {
        timeoutReached = true;
        controller.abort();
    }, REQUEST_TIMEOUT_MS);
    const abort = () => controller.abort();

    if (signal?.aborted) {
        controller.abort();
    } else {
        signal?.addEventListener("abort", abort, {once: true});
    }

    return {
        signal: controller.signal,
        cleanup: () => {
            window.clearTimeout(timeoutId);
            signal?.removeEventListener("abort", abort);
        },
        timedOut: () => timeoutReached,
    };
}

export async function request<T>(
    path: string,
    init: RequestInit = {},
): Promise<T> {
    let response: Response;
    const requestSignal = createRequestSignal(init.signal ?? undefined);
    const token = getApiToken();
    try {
        response = await fetch(`${API_BASE}${path}`, {
            ...init,
            signal: requestSignal.signal,
            headers: {
                "Content-Type": "application/json",
                ...(token ? {Authorization: `Bearer ${token}`} : {}),
                ...(init.headers ?? {}),
            },
        });
    } catch (error) {
        if (requestSignal.timedOut()) {
            throw new ApiError(
                `请求 Argus API 超时，请稍后重试：${path}`,
                0,
                "REQUEST_TIMEOUT",
                {path, timeoutMs: REQUEST_TIMEOUT_MS},
            );
        }
        if (error instanceof DOMException && error.name === "AbortError") {
            throw new ApiError("请求已取消。", 0, "REQUEST_ABORTED", {path});
        }
        throw new ApiError(
            error instanceof Error ? `无法连接 Argus API：${error.message}` : "无法连接 Argus API。",
            0,
            "NETWORK_ERROR",
            {path},
        );
    } finally {
        requestSignal.cleanup();
    }

    if (response.status === 204) {
        return undefined as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const body = await parseResponseBody<T>(response, contentType);

    if (!response.ok) {
        if (response.status === 401) requireApiToken();
        const apiError = apiErrorFromBody(body, response.status);
        if (apiError) throw apiError;
        throw new ApiError(`请求失败：HTTP ${response.status}`, response.status, "HTTP_ERROR", {
            responseBody: body,
        });
    }

    return body as T;
}

export async function requestBlob(path: string): Promise<Blob> {
    const token = getApiToken();
    let response: Response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            headers: token ? {Authorization: `Bearer ${token}`} : {},
        });
    } catch (error) {
        throw new ApiError(
            error instanceof Error ? `无法下载资源：${error.message}` : "无法下载资源。",
            0,
            "NETWORK_ERROR",
            {path},
        );
    }
    if (response.status === 401) requireApiToken();
    if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const body = await parseResponseBody<unknown>(response, contentType);
        throw apiErrorFromBody(body, response.status)
            ?? new ApiError(`资源请求失败：HTTP ${response.status}`, response.status);
    }
    return response.blob();
}

export async function loadObjectUrl(path: string): Promise<string> {
    return URL.createObjectURL(await requestBlob(path));
}

export async function openAuthenticatedResource(path: string, filename?: string): Promise<void> {
    const popup = filename ? null : window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    let objectUrl: string;
    try {
        objectUrl = await loadObjectUrl(path);
    } catch (error) {
        popup?.close();
        throw error;
    }
    if (filename) {
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = filename;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
        return;
    }
    if (popup) popup.location.replace(objectUrl);
    else window.open(objectUrl, "_blank", "noopener");
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

export function reportUrl(taskId: string, json = false, download = false): string {
    const path = `${API_BASE}/tasks/${encodeURIComponent(taskId)}/${json ? "report.json" : "report"}`;
    return download ? `${path}?download=true` : path;
}

export function reportPath(taskId: string, json = false, download = false): string {
    const path = `/tasks/${encodeURIComponent(taskId)}/${json ? "report.json" : "report"}`;
    return download ? `${path}?download=true` : path;
}

export function screenshotUrl(taskId: string, screenshotPath: string): string {
    const filename = screenshotPath.replace(/\\/g, "/").split("/").pop() ?? "";
    return `${API_BASE}/tasks/${encodeURIComponent(taskId)}/screenshots/${encodeURIComponent(filename)}`;
}

export function screenshotPath(taskId: string, rawPath: string): string {
    const filename = rawPath.replace(/\\/g, "/").split("/").pop() ?? "";
    return `/tasks/${encodeURIComponent(taskId)}/screenshots/${encodeURIComponent(filename)}`;
}

export function debugBundleUrl(taskId: string): string {
    return `${API_BASE}/tasks/${encodeURIComponent(taskId)}/debug-bundle`;
}

export function debugBundlePath(taskId: string): string {
    return `/tasks/${encodeURIComponent(taskId)}/debug-bundle`;
}
