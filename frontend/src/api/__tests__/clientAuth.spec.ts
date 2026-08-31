import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authRequired, clearApiToken, setApiToken } from "../../auth";
import { loadObjectUrl, request, requestBlob } from "../client";
import { TaskEventStream } from "../../ws";

class MockWebSocket {
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = 0;
  private listeners = new Map<string, (() => void)[]>();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: () => void): void {
    const callbacks = this.listeners.get(type) ?? [];
    callbacks.push(listener);
    this.listeners.set(type, callbacks);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSING;
  }
}

describe("API session token", () => {
  beforeEach(() => {
    clearApiToken();
    authRequired.value = false;
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearApiToken();
  });

  it("attaches the session token as a Bearer header", async () => {
    setApiToken("secret-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await request<{ ok: boolean }>("/health");

    expect(fetchMock).toHaveBeenCalledOnce();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toMatchObject({ Authorization: "Bearer secret-token" });
    expect(sessionStorage.getItem("argus.apiToken")).toBe("secret-token");
  });

  it("opens the unlock state after a 401 response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: "UNAUTHORIZED", message: "需要有效的 API Token。" },
          }),
          { status: 401, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(request("/tasks")).rejects.toMatchObject({ status: 401 });
    expect(authRequired.value).toBe(true);
  });

  it("uses a short-lived ticket (not the long token) in WebSocket URLs", async () => {
    setApiToken("token +/?&中文");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ token: "short-lived-ticket", expiresIn: 30, singleUse: true }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        ),
    );
    const stream = new TaskEventStream();
    const internal = stream as unknown as {
      endpoint: string;
      openSocket: (endpoint: string, sinceSeq?: number, epoch?: string) => Promise<void>;
    };
    // 复刻 connect() 的准备工作：openSocket 前先登记当前 endpoint，
    // 避免 ticket 换取期间被 stale-guard 判定为"已切换端点"而中止。
    const endpoint = "ws://localhost/argus/api/ws/tasks/task%2Fwith%20space";
    internal.endpoint = endpoint;
    await internal.openSocket(endpoint, 42, "ev-20260810-abcdef12");

    const created = new URL(MockWebSocket.instances[0].url);
    expect(created.pathname).toContain("/ws/tasks/task%2Fwith%20space");
    expect(created.searchParams.get("sinceSeq")).toBe("42");
    // 重连时携带上次连接的纪元，服务端据此识别服务重启后的 sequence 空间不连续。
    expect(created.searchParams.get("epoch")).toBe("ev-20260810-abcdef12");
    // 长期 Token 不进入 WebSocket query：换成了短时、单次 ticket。
    expect(created.searchParams.get("token")).toBe("short-lived-ticket");
    expect(created.searchParams.get("token")).not.toBe("token +/?&中文");
    stream.close();
  });

  it("loads protected binary resources through authenticated fetch", async () => {
    setApiToken("blob-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(["data"]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:argus-test"),
      revokeObjectURL: vi.fn(),
    });

    await expect(loadObjectUrl("/tasks/t/report")).resolves.toBe("blob:argus-test");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toMatchObject({ Authorization: "Bearer blob-token" });
  });

  it("aborts protected binary resources through the caller signal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }),
    );
    const controller = new AbortController();

    const pending = requestBlob("/tasks/t/report", controller.signal);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ code: "REQUEST_ABORTED" });
  });

  it("preserves structured errors from protected binary resources", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: "REPORT_NOT_FOUND", message: "报告不存在。" },
          }),
          { status: 404, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(requestBlob("/tasks/t/report")).rejects.toMatchObject({
      status: 404,
      code: "REPORT_NOT_FOUND",
    });
  });

  it("times out protected binary resources", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }),
    );

    const pending = requestBlob("/tasks/t/report");
    const rejection = expect(pending).rejects.toMatchObject({ code: "REQUEST_TIMEOUT" });
    await vi.advanceTimersByTimeAsync(180_000);

    await rejection;
  });
});
