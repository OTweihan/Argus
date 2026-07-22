import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authRequired, clearApiToken, setApiToken } from "../../auth";
import { loadObjectUrl, request } from "../client";
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
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearApiToken();
  });

  it("attaches the session token as a Bearer header", async () => {
    setApiToken("secret-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ok: true}), {
      status: 200,
      headers: {"content-type": "application/json"},
    }));
    vi.stubGlobal("fetch", fetchMock);

    await request<{ok: boolean}>("/health");

    expect(fetchMock).toHaveBeenCalledOnce();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toMatchObject({Authorization: "Bearer secret-token"});
    expect(sessionStorage.getItem("argus.apiToken")).toBe("secret-token");
  });

  it("opens the unlock state after a 401 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {code: "UNAUTHORIZED", message: "需要有效的 API Token。"},
    }), {status: 401, headers: {"content-type": "application/json"}})));

    await expect(request("/tasks")).rejects.toMatchObject({status: 401});
    expect(authRequired.value).toBe(true);
  });

  it("encodes token and sequence independently in WebSocket URLs", () => {
    setApiToken("token +/?&中文");
    const stream = new TaskEventStream();
    const internal = stream as unknown as {
      openSocket: (endpoint: string, sinceSeq?: number) => void;
    };
    internal.openSocket("ws://localhost/argus/api/ws/tasks/task%2Fwith%20space", 42);

    const created = new URL(MockWebSocket.instances[0].url);
    expect(created.pathname).toContain("/ws/tasks/task%2Fwith%20space");
    expect(created.searchParams.get("sinceSeq")).toBe("42");
    expect(created.searchParams.get("token")).toBe("token +/?&中文");
    stream.close();
  });

  it("loads protected binary resources through authenticated fetch", async () => {
    setApiToken("blob-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(["data"]), {status: 200}));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:argus-test"),
      revokeObjectURL: vi.fn(),
    });

    await expect(loadObjectUrl("/tasks/t/report")).resolves.toBe("blob:argus-test");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toMatchObject({Authorization: "Bearer blob-token"});
  });
});
