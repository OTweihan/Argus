/** correlation API wrapper 测试：URL 构建、参数编码、端点完整性。 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCaptureQuality,
  getCorrelationSummary,
  listCorrelationRunsByTask,
  listEndpointEvidence,
  listFindingEvidence,
  listUncoveredEndpoints,
  listUnmatchedRequests,
} from "../correlation/index";

describe("correlation API wrapper", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Summary ─────────────────────────────────────────────────

  it("getCorrelationSummary 构建正确的 URL", async () => {
    await getCorrelationSummary("cr-1");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/correlation-runs/cr-1/summary");
  });

  // ── Endpoint Evidence ───────────────────────────────────────

  it("listEndpointEvidence 默认无查询参数", async () => {
    await listEndpointEvidence("cr-1");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/argus/api/correlation-runs/cr-1/endpoint-evidence");
  });

  it("listEndpointEvidence 附带过滤参数", async () => {
    await listEndpointEvidence("cr-1", {
      resolutionStatus: "UNIQUE",
      matchStrategy: "EXACT",
      offset: 20,
      limit: 50,
    });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("resolutionStatus=UNIQUE");
    expect(url).toContain("matchStrategy=EXACT");
    expect(url).toContain("offset=20");
    expect(url).toContain("limit=50");
  });

  it("listEndpointEvidence offset=0 时仍附加 offset 参数", async () => {
    // offset=0 仍然会附加（0 !== undefined），与 offset 未传的行为一致
    await listEndpointEvidence("cr-1", { offset: 0 });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("offset=0");
  });

  // ── Unmatched Requests ──────────────────────────────────────

  it("listUnmatchedRequests 构建正确的 URL 包含分页参数", async () => {
    await listUnmatchedRequests("cr-1", 10, 25);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/correlation-runs/cr-1/unmatched-requests");
    expect(url).toContain("offset=10");
    expect(url).toContain("limit=25");
  });

  // ── Finding Evidence ────────────────────────────────────────

  it("listFindingEvidence 构建正确的 URL", async () => {
    await listFindingEvidence("cr-1", 0, 50);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/correlation-runs/cr-1/finding-evidence");
    expect(url).toContain("offset=0");
    expect(url).toContain("limit=50");
  });

  // ── Uncovered Endpoints ─────────────────────────────────────

  it("listUncoveredEndpoints 构建正确的 URL", async () => {
    await listUncoveredEndpoints("cr-1", 5, 30);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/correlation-runs/cr-1/uncovered-endpoints");
    expect(url).toContain("offset=5");
    expect(url).toContain("limit=30");
  });

  // ── CaptureQuality ──────────────────────────────────────────

  it("getCaptureQuality 构建正确的 URL", async () => {
    await getCaptureQuality("cr-1");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/correlation-runs/cr-1/capture-quality");
  });

  // ── 任务级查询 ──────────────────────────────────────────────

  it("listCorrelationRunsByTask 构建正确的 URL", async () => {
    await listCorrelationRunsByTask("task-1");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/correlation-runs?taskId=task-1");
  });

  it("listCorrelationRunsByTask 编码含特殊字符的 taskId", async () => {
    await listCorrelationRunsByTask("t/id+test");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("taskId=t%2Fid%2Btest");
  });
});
