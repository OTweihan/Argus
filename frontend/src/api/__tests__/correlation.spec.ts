/** correlation API wrapper 测试：URL 构建、参数编码、端点完整性。 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    bindAnalysis,
    getAttempt,
    getCaptureQuality,
    getCorrelationRun,
    getCorrelationSummary,
    listAttempts,
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

    // ── CorrelationRun ──────────────────────────────────────────

    it("getCorrelationRun 构建正确的 URL", async () => {
        await getCorrelationRun("cr-1");
        expect(fetchMock).toHaveBeenCalledOnce();
        const url = fetchMock.mock.calls[0][0] as string;
        expect(url).toContain("/correlation-runs/cr-1");
    });

    it("getCorrelationRun 对含特殊字符的 ID 进行编码", async () => {
        await getCorrelationRun("cr/a+b c");
        const url = fetchMock.mock.calls[0][0] as string;
        expect(url).toContain("cr%2Fa%2Bb%20c");
        expect(url).not.toContain("cr/a+b c");
    });

    // ── Attempts ────────────────────────────────────────────────

    it("listAttempts 构建正确的 URL", async () => {
        await listAttempts("cr-1");
        const url = fetchMock.mock.calls[0][0] as string;
        expect(url).toContain("/correlation-runs/cr-1/attempts");
    });

    it("getAttempt 同时编码 runId 和 attemptId", async () => {
        await getAttempt("run/x", "att/y");
        const url = fetchMock.mock.calls[0][0] as string;
        expect(url).toContain("/correlation-runs/run%2Fx/attempts/att%2Fy");
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

    // ── BindAnalysis ────────────────────────────────────────────

    it("bindAnalysis 发送 POST 请求含 JSON body", async () => {
        await bindAnalysis("cr-1", "analysis-42", 3, true, "version mismatch");
        expect(fetchMock).toHaveBeenCalledOnce();
        const url = fetchMock.mock.calls[0][0] as string;
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        expect(url).toContain("/correlation-runs/cr-1/bind-analysis");
        expect(init.method).toBe("POST");
        const body = JSON.parse(init.body as string);
        expect(body.analysisId).toBe("analysis-42");
        expect(body.expectedProjectionVersion).toBe(3);
        expect(body.sourceMismatchOverride).toBe(true);
        expect(body.sourceMismatchOverrideReason).toBe("version mismatch");
    });

    it("bindAnalysis 不传 override 时默认使用 false/null", async () => {
        await bindAnalysis("cr-1", "analysis-1");
        const body = JSON.parse(
            (fetchMock.mock.calls[0][1] as RequestInit).body as string,
        );
        expect(body.sourceMismatchOverride).toBe(false);
        expect(body.sourceMismatchOverrideReason).toBeNull();
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
