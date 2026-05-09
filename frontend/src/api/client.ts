const API_BASE = (import.meta.env.VITE_ARGUS_API_BASE ?? "/api/v1").replace(/\/$/, "");

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
    error?: { code: string; message: string; details?: Record<string, unknown> };
}

async function parseResponseBody<T>(
    response: Response,
    contentType: string,
): Promise<T | ApiErrorBody | string> {
    if (!contentType.includes("application/json")) {
        return response.text();
    }
    try {
        return (await response.json()) as T | ApiErrorBody;
    } catch {
        throw new ApiError(
            `服务返回了无效 JSON：HTTP ${response.status}`,
            response.status,
            "INVALID_JSON_RESPONSE",
        );
    }
}

export async function request<T>(
    path: string,
    init: RequestInit = {},
): Promise<T> {
    let response: Response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            ...init,
            headers: {
                "Content-Type": "application/json",
                ...(init.headers ?? {}),
            },
        });
    } catch (error) {
        throw new ApiError(
            error instanceof Error ? `无法连接 Argus API：${error.message}` : "无法连接 Argus API。",
            0,
            "NETWORK_ERROR",
        );
    }

    if (response.status === 204) {
        return undefined as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const body = await parseResponseBody<T>(response, contentType);

    if (!response.ok) {
        const error =
            typeof body === "object" && body !== null
                ? (body as ApiErrorBody).error
                : undefined;
        throw new ApiError(
            error?.message ?? `请求失败：HTTP ${response.status}`,
            response.status,
            error?.code,
            error?.details,
        );
    }

    return body as T;
}

export function reportUrl(taskId: string, json = false, download = false): string {
    const path = `${API_BASE}/tasks/${encodeURIComponent(taskId)}/${json ? "report.json" : "report"}`;
    return download ? `${path}?download=true` : path;
}

export function screenshotUrl(taskId: string, screenshotPath: string): string {
    const filename = screenshotPath.replace(/\\/g, "/").split("/").pop() ?? "";
    return `${API_BASE}/tasks/${encodeURIComponent(taskId)}/screenshots/${encodeURIComponent(filename)}`;
}
