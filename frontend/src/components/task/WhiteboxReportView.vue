<template>
  <div v-loading="loading" class="wb-report">
    <template v-if="error">
      <el-empty :description="error || '加载失败'" />
    </template>
    <template v-else-if="summary">
      <section class="report-hero" aria-labelledby="whitebox-report-title">
        <div class="hero-copy">
          <span class="hero-kicker">WHITEBOX ANALYSIS</span>
          <h2 id="whitebox-report-title">白盒分析报告</h2>
          <p>查看源码解析质量、调用关系与风险发现，快速判断本次分析结果是否可信。</p>
        </div>
        <AnalysisRunSelector
          :runs="runs"
          :selected-id="analysisId"
          :loading="loading"
          @select="onSelectRun"
        />
      </section>

      <div class="report-summary">
        <AnalysisSnapshotBar :summary="summary" />
        <CompletenessBanner :summary="summary" />
      </div>

      <el-tabs v-model="subTab" class="report-tabs">
        <el-tab-pane lazy label="概览" name="overview">
          <OverviewTab :summary="summary" />
        </el-tab-pane>
        <el-tab-pane lazy label="端点" name="endpoints">
          <EndpointList
            :items="endpoints.items"
            :total="endpoints.total"
            :has-more="endpoints.hasMore"
            :loading="endpoints.loading"
            @load-more="endpoints.loadMore"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="调用关系" name="callgraph">
          <CallGraphViewer
            :items="callNodes.items"
            :total="callNodes.total"
            :has-more="callNodes.hasMore"
            :loading="callNodes.loading"
            :callee-items="calleeItems"
            :callee-loading="calleeLoading"
            :selected-node-id="selectedCallNodeId"
            @load-more="callNodes.loadMore"
            @select-node="selectCallNode"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="执行流" name="flows">
          <ExecutionFlowList
            :items="flows.items"
            :has-more="flows.hasMore"
            :loading="flows.loading"
            @load-more="flows.loadMore"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="诊断" name="diagnostics" class="diagnostics-pane">
          <DiagnosticsPanel :diagnostics="diagnostics" />
        </el-tab-pane>
        <el-tab-pane lazy label="聚类" name="clusters">
          <ClusterList
            :items="clusters.items"
            :total="clusters.total"
            :has-more="clusters.hasMore"
            :loading="clusters.loading"
            @load-more="clusters.loadMore"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="发现项" name="findings">
          <FindingList
            :items="findings.items"
            :total="findings.total"
            :has-more="findings.hasMore"
            :loading="findings.loading"
            @load-more="findings.loadMore"
          />
        </el-tab-pane>
        <el-tab-pane v-if="correlationRunId" lazy label="关联证据" name="correlation">
          <CorrelationTab :correlation-run-id="correlationRunId" />
        </el-tab-pane>
      </el-tabs>

      <el-backtop
        v-if="showBackTop"
        target=".wb-report"
        :visibility-height="180"
        :right="28"
        :bottom="24"
        class="report-backtop"
        aria-label="返回报告顶部"
      >
        <span class="backtop-content">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3.5 9.5 8 5l4.5 4.5" />
          </svg>
          返回顶部
        </span>
      </el-backtop>
    </template>
    <el-empty v-else description="暂无分析执行数据，请先启动白盒任务" />
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from "vue";
import type {
  AnalysisRunSummary,
  CallEdgeInfo,
  CallNodeInfo,
  ClusterInfo,
  DiagnosticsInfo,
  EndpointInfo,
  ExecutionFlowInfo,
  FindingInfo,
} from "../../api/task";
import {
  getAnalysisDiagnostics,
  getAnalysisRunSummary,
  listAnalysisCallEdges,
  listAnalysisCallNodes,
  listAnalysisClusters,
  listAnalysisEndpoints,
  listAnalysisExecutionFlows,
  listAnalysisFindings,
  listAnalysisRuns,
} from "../../api/task";
import { errorMessage } from "../../utils";
import { usePagedList, type PagedResult } from "../../composables/usePagedList";
import OverviewTab from "./whitebox/OverviewTab.vue";
import AnalysisRunSelector from "./whitebox/AnalysisRunSelector.vue";
import AnalysisSnapshotBar from "./whitebox/AnalysisSnapshotBar.vue";
import CompletenessBanner from "./whitebox/CompletenessBanner.vue";
import EndpointList from "./whitebox/EndpointList.vue";
import CallGraphViewer from "./whitebox/CallGraphViewer.vue";
import ExecutionFlowList from "./whitebox/ExecutionFlowList.vue";
import DiagnosticsPanel from "./whitebox/DiagnosticsPanel.vue";
import ClusterList from "./whitebox/ClusterList.vue";
import FindingList from "./whitebox/FindingList.vue";
import CorrelationTab from "./whitebox/CorrelationTab.vue";

// correlationRunId 由父级 TasksView 作为单一 owner 查询后经 prop 传入（F-M3），
// 本组件不再自行调用 listCorrelationRunsByTask，避免任务打开时重复请求。
const props = defineProps<{ taskId: string; correlationRunId?: string | null }>();

const summary = ref<AnalysisRunSummary | null>(null);
const runs = ref<AnalysisRunSummary[]>([]);
const analysisId = ref<string | null>(null);
const loading = ref(false);
const error = ref("");
const subTab = ref("overview");
const SCROLLABLE_TABS = new Set([
  "endpoints",
  "callgraph",
  "flows",
  "clusters",
  "findings",
  "correlation",
]);
const showBackTop = computed(() => SCROLLABLE_TABS.has(subTab.value));

// 初始化：加载历史列表 + 默认选择最新（关联运行已由父级查询并传入）
// F7：AbortController 守卫——组件卸载/切换时中止在途首屏请求，避免晚到响应写入
// 已卸载组件或旧 taskId 覆盖新数据。
let initialLoadAbort: AbortController | null = null;
let selectRunAbort: AbortController | null = null;
let calleeAbort: AbortController | null = null;
(async () => {
  const controller = new AbortController();
  initialLoadAbort = controller;
  loading.value = true;
  try {
    const page = await listAnalysisRuns(props.taskId, undefined, undefined, {
      signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    runs.value = page.items;
    if (page.items.length > 0) {
      const running = page.items.find((r: AnalysisRunSummary) => r.runStatus === "RUNNING");
      const succeeded = page.items.find((r: AnalysisRunSummary) => r.runStatus === "SUCCEEDED");
      const selected = running || succeeded || page.items[0];
      analysisId.value = selected.analysisId;
      summary.value = await getAnalysisRunSummary(props.taskId, selected.analysisId, {
        signal: controller.signal,
      });
    }
  } catch (e) {
    if (!controller.signal.aborted) error.value = errorMessage(e);
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
})();

async function onSelectRun(aid: string): Promise<void> {
  resetSubResources();
  analysisId.value = aid;
  // 始终调用详情接口获取完整的 completeness/severity/metrics 数据，
  // 列表接口只返回计数和严重级别分布，不含完整性指标与质量问题。
  // F7：切换 run 时中止上一次详情请求，避免旧 run 的响应覆盖新 run。
  selectRunAbort?.abort();
  const controller = new AbortController();
  selectRunAbort = controller;
  loading.value = true;
  try {
    summary.value = await getAnalysisRunSummary(props.taskId, aid, {
      signal: controller.signal,
    });
  } catch (e) {
    if (!controller.signal.aborted) error.value = errorMessage(e);
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
}

onUnmounted(() => {
  initialLoadAbort?.abort();
  selectRunAbort?.abort();
  calleeAbort?.abort();
  diagAbort?.abort();
});

// ── 分页子资源（usePagedList 统一管理 load/loadMore/cursor/loading） ──

// F1：五个子资源列表仅 fetcher 与 limit 不同，抽工厂收敛「usePagedList + 解构 +
// load/loadMore wrapper」样板；reactive 包装让模板可直接访问解包后的 items 等。
function makeCursorList<T>(
  fetcher: (
    p: { cursor: string | null; limit: number },
    aid: string,
    signal?: AbortSignal,
  ) => Promise<PagedResult<T>>,
  limit: number,
) {
  const list = usePagedList<T, [string]>(
    // 透传 usePagedList 管理的中止信号：切 run / 卸载时真正取消在途请求
    // （而非仅丢弃响应）。
    (pagination, aid) => fetcher({ cursor: pagination.cursor, limit }, aid, pagination.signal),
    { limit, cursor: true },
  );
  const guarded = (action: (aid: string) => Promise<void>) => (): void => {
    const aid = analysisId.value;
    if (aid) void action(aid);
  };
  return reactive({
    items: list.items,
    total: list.total,
    hasMore: list.hasMore,
    loading: list.loading,
    load: guarded((aid) => list.load(aid)),
    loadMore: guarded((aid) => list.loadMore(aid)),
    reset: list.reset,
  });
}

const endpoints = makeCursorList<EndpointInfo>(
  ({ cursor, limit }, aid, signal) =>
    listAnalysisEndpoints(props.taskId, aid, cursor, limit, { signal }),
  100,
);
const callNodes = makeCursorList<CallNodeInfo>(
  ({ cursor, limit }, aid, signal) =>
    listAnalysisCallNodes(props.taskId, aid, null, null, cursor, limit, { signal }),
  100,
);
const flows = makeCursorList<ExecutionFlowInfo>(
  ({ cursor, limit }, aid, signal) =>
    listAnalysisExecutionFlows(props.taskId, aid, cursor, limit, { signal }),
  50,
);
const findings = makeCursorList<FindingInfo>(
  ({ cursor, limit }, aid, signal) =>
    listAnalysisFindings(props.taskId, aid, cursor, limit, { signal }),
  50,
);
const clusters = makeCursorList<ClusterInfo>(
  ({ cursor, limit }, aid, signal) =>
    listAnalysisClusters(props.taskId, aid, cursor, limit, { signal }),
  50,
);

// Callee edges（选中调用节点的下一层，非分页列表，保留手写）
const selectedCallNodeId = ref<string | null>(null);
const calleeItems = ref<CallEdgeInfo[]>([]);
const calleeLoading = ref(false);

async function selectCallNode(nodeId: string): Promise<void> {
  const aid = analysisId.value;
  if (!aid) return;
  if (selectedCallNodeId.value === nodeId) {
    selectedCallNodeId.value = null;
    calleeItems.value = [];
    calleeLoading.value = false;
    calleeAbort?.abort();
    calleeAbort = null;
    return;
  }
  selectedCallNodeId.value = nodeId;
  calleeItems.value = [];
  calleeLoading.value = true;
  // F8：切换节点时中止上一个 callee-edges 请求，避免浪费带宽（身份校验兜底仍在）。
  calleeAbort?.abort();
  const controller = new AbortController();
  calleeAbort = controller;
  try {
    const page = await listAnalysisCallEdges(props.taskId, aid, nodeId, null, 50, {
      signal: controller.signal,
    });
    if (selectedCallNodeId.value === nodeId) {
      calleeItems.value = page.items;
    }
  } catch (caught) {
    if (!controller.signal.aborted)
      console.warn("[WhiteboxReport] 调用边加载失败：", errorMessage(caught));
  } finally {
    if (selectedCallNodeId.value === nodeId) {
      calleeLoading.value = false;
    }
  }
}

// Diagnostics（非分页，tab 切换时懒加载一次）
const diagnostics = ref<DiagnosticsInfo | null>(null);
let diagLoaded = false;
let diagAbort: AbortController | null = null;

async function loadDiagnostics(): Promise<void> {
  const aid = analysisId.value;
  if (!aid || diagLoaded) return;
  // 与 summary/callee 相同的 abort + 身份校验口径：切换 run 时丢弃过期响应，
  // 防止慢响应把旧 run 的诊断串台到新 run。
  diagAbort?.abort();
  const controller = new AbortController();
  diagAbort = controller;
  try {
    const result = await getAnalysisDiagnostics(props.taskId, aid, {
      signal: controller.signal,
    });
    if (controller.signal.aborted || aid !== analysisId.value) return;
    diagnostics.value = result;
    diagLoaded = true;
  } catch (caught) {
    if (controller.signal.aborted || aid !== analysisId.value) return;
    // 诊断为尽力而为展示，失败不阻塞页面，仅记录便于排查。
    console.warn("[WhiteboxReport] 诊断信息加载失败：", errorMessage(caught));
  }
}

function resetSubResources(): void {
  endpoints.reset();
  callNodes.reset();
  flows.reset();
  findings.reset();
  clusters.reset();
  diagAbort?.abort();
  diagAbort = null;
  diagnostics.value = null;
  diagLoaded = false;
  selectedCallNodeId.value = null;
  calleeItems.value = [];
  calleeLoading.value = false;
  // 切 run 时中止在途 callee-edges 请求（身份校验已兜底，但这里显式释放请求）。
  calleeAbort?.abort();
  calleeAbort = null;
}

/** 按当前激活的 tab 懒加载对应子资源。
 *
 * 以「列表为空才加载」作为门控：既保证 B2（切 run / 首次打开 tab 才拉取），
 * 又避免切回已加载过的 tab 时重置分页/滚动状态（只对空列表发请求）。
 * 加载失败时列表保持为空，下次切回会自动重试。
 */
function loadCurrentTabResources(): void {
  if (!analysisId.value) return;
  if (subTab.value === "endpoints" && endpoints.items.length === 0) endpoints.load();
  if (subTab.value === "callgraph" && callNodes.items.length === 0) callNodes.load();
  if (subTab.value === "flows" && flows.items.length === 0) flows.load();
  if (subTab.value === "diagnostics") loadDiagnostics();
  if (subTab.value === "findings" && findings.items.length === 0) findings.load();
  if (subTab.value === "clusters" && clusters.items.length === 0) clusters.load();
}

// analysisId 变化（含初始化与切 run）→ 加载当前 tab 资源
watch(analysisId, (aid) => {
  if (aid) loadCurrentTabResources();
});

// subTab 变化 → 懒加载该 tab 资源
watch(subTab, () => loadCurrentTabResources());
</script>

<style scoped>
.wb-report {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 18px 8px 18px;
  background:
    radial-gradient(circle at 0 0, rgba(10, 186, 181, 0.08), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.58), rgba(248, 250, 252, 0.35));
}

.wb-report > .report-hero,
.wb-report > .report-summary,
.wb-report > .report-tabs {
  width: min(1440px, 100%);
  margin-right: auto;
  margin-left: auto;
}

.report-hero {
  position: relative;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 24px;
  overflow: hidden;
  border: 1px solid rgba(10, 186, 181, 0.22);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(120deg, rgba(255, 255, 255, 0.96), rgba(236, 254, 253, 0.88)),
    var(--surface-solid);
  box-shadow: var(--shadow-panel);
}

.report-hero::after {
  content: "";
  position: absolute;
  width: 220px;
  height: 220px;
  right: -88px;
  top: -132px;
  border-radius: 50%;
  background: rgba(10, 186, 181, 0.12);
  pointer-events: none;
}

.hero-copy {
  position: relative;
  z-index: 1;
  min-width: 0;
}

.hero-kicker {
  display: inline-flex;
  margin-bottom: 7px;
  color: var(--brand-700);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.hero-copy h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: clamp(22px, 2.4vw, 30px);
  line-height: 1.2;
  letter-spacing: -0.025em;
}

.hero-copy p {
  margin: 8px 0 0;
  max-width: 650px;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.65;
}

.report-summary {
  display: grid;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1.65fr) minmax(280px, 0.8fr);
  gap: 12px;
  margin-top: 14px;
  margin-bottom: 14px;
}

.report-tabs {
  display: flex;
  flex: 1 0 auto;
  min-height: 300px;
  padding: 0 16px 8px;
  flex-direction: column;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-panel);
}

.report-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin: 0 -16px 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line-soft);
  background: rgba(248, 250, 252, 0.78);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}

.report-tabs :deep(.el-tabs__content) {
  flex: 1;
}

.report-tabs :deep(.el-tab-pane) {
  min-height: 100%;
  animation: report-pane-enter 180ms ease-out;
}

.report-tabs :deep(.diagnostics-pane) {
  height: 100%;
}

.report-tabs :deep(.el-tabs__item) {
  height: 50px;
  color: var(--text-muted);
  font-weight: 600;
}

.report-tabs :deep(.el-tabs__item.is-active) {
  color: var(--brand-700);
}

.report-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: var(--radius-pill);
  background: var(--brand-gradient);
}

.report-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.report-tabs :deep(.el-table) {
  --el-table-border-color: var(--line-soft);
  --el-table-header-bg-color: #f3fbfa;
  overflow: hidden;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
}

.report-tabs :deep(.el-table th.el-table__cell) {
  color: var(--text-muted);
  font-weight: 700;
}

/* 嵌入白盒报告时只保留报告本身这一层纵向滚动，避免关联证据形成双滚动区。 */
.report-tabs :deep(.corr-container) {
  overflow-y: visible;
}

.report-tabs :deep(.el-input__wrapper:focus-within) {
  box-shadow:
    0 0 0 1px var(--brand-500) inset,
    var(--shadow-ring);
}

.report-backtop {
  width: 94px;
  height: 40px;
  color: var(--brand-700);
  border: 1px solid rgba(10, 186, 181, 0.28);
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 28px -12px rgba(8, 123, 120, 0.45);
  backdrop-filter: blur(10px);
}

.report-backtop:hover {
  color: #fff;
  border-color: transparent;
  background: var(--brand-700);
  transform: translateY(-2px);
}

.backtop-content {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 700;
}

.backtop-content svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

@keyframes report-pane-enter {
  from {
    opacity: 0;
    transform: translateY(5px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 960px) {
  .report-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .report-summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .wb-report {
    padding: 10px;
  }

  .report-hero {
    padding: 18px;
    border-radius: var(--radius-md);
  }

  .report-tabs {
    padding-inline: 10px;
  }

  .report-tabs :deep(.el-tabs__header) {
    margin-inline: -10px;
    padding-inline: 10px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wb-report *,
  .wb-report *::before,
  .wb-report *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
