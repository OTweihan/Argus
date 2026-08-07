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
            :items="endpointItems"
            :total="endpointTotal"
            :has-more="endpointHasMore"
            :loading="endpointLoading"
            @load-more="loadMoreEndpoints"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="调用关系" name="callgraph">
          <CallGraphViewer
            :items="callNodeItems"
            :total="callNodeTotal"
            :has-more="callNodeHasMore"
            :loading="callNodeLoading"
            :callee-items="calleeItems"
            :callee-loading="calleeLoading"
            :selected-node-id="selectedCallNodeId"
            @load-more="loadMoreCallNodes"
            @select-node="selectCallNode"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="执行流" name="flows">
          <ExecutionFlowList
            :items="flowItems"
            :has-more="flowHasMore"
            :loading="flowLoading"
            @load-more="loadMoreFlows"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="诊断" name="diagnostics" class="diagnostics-pane">
          <DiagnosticsPanel :diagnostics="diagnostics" />
        </el-tab-pane>
        <el-tab-pane lazy label="聚类" name="clusters">
          <ClusterList
            :items="clusterItems"
            :total="clusterTotal"
            :has-more="clusterHasMore"
            :loading="clusterLoading"
            @load-more="loadMoreClusters"
          />
        </el-tab-pane>
        <el-tab-pane lazy label="发现项" name="findings">
          <FindingList
            :items="findingItems"
            :total="findingTotal"
            :has-more="findingHasMore"
            :loading="findingLoading"
            @load-more="loadMoreFindings"
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
import { computed, ref, watch } from "vue";
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
import { usePagedList } from "../../composables/usePagedList";
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
import { listCorrelationRunsByTask } from "../../api/correlation";

const props = defineProps<{ taskId: string }>();

const summary = ref<AnalysisRunSummary | null>(null);
const runs = ref<AnalysisRunSummary[]>([]);
const analysisId = ref<string | null>(null);
const loading = ref(false);
const error = ref("");
const subTab = ref("overview");
const correlationRunId = ref<string | null>(null);
const SCROLLABLE_TABS = new Set(["endpoints", "callgraph", "flows", "clusters", "findings", "correlation"]);
const showBackTop = computed(() => SCROLLABLE_TABS.has(subTab.value));

// 初始化：加载历史列表 + 默认选择最新 + 检查关联
(async () => {
  loading.value = true;
  try {
    const page = await listAnalysisRuns(props.taskId);
    runs.value = page.items;
    if (page.items.length > 0) {
      const running = page.items.find((r: AnalysisRunSummary) => r.runStatus === "RUNNING");
      const succeeded = page.items.find((r: AnalysisRunSummary) => r.runStatus === "SUCCEEDED");
      const selected = running || succeeded || page.items[0];
      analysisId.value = selected.analysisId;
      summary.value = await getAnalysisRunSummary(props.taskId, selected.analysisId);
    }
    // 检查是否存在关联运行
    const crs = await listCorrelationRunsByTask(props.taskId);
    if (crs.length > 0) {
      correlationRunId.value = crs[0].correlationRunId;
    }
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
})();

async function onSelectRun(aid: string): Promise<void> {
  resetSubResources();
  analysisId.value = aid;
  // 始终调用详情接口获取完整的 completeness/severity/metrics 数据，
  // 列表接口只返回计数和严重级别分布，不含完整性指标与质量问题。
  loading.value = true;
  try {
    summary.value = await getAnalysisRunSummary(props.taskId, aid);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
}

// ── 分页子资源（usePagedList 统一管理 load/loadMore/cursor/loading） ──

const endpointsList = usePagedList<EndpointInfo, [string]>(
  (p, aid) => listAnalysisEndpoints(props.taskId, aid, p.cursor, p.limit),
  { limit: 100, cursor: true },
);
const {
  items: endpointItems,
  total: endpointTotal,
  hasMore: endpointHasMore,
  loading: endpointLoading,
} = endpointsList;
function loadEndpoints(): void {
  const aid = analysisId.value;
  if (aid) void endpointsList.load(aid);
}
function loadMoreEndpoints(): void {
  const aid = analysisId.value;
  if (aid) void endpointsList.loadMore(aid);
}

const callNodesList = usePagedList<CallNodeInfo, [string]>(
  (p, aid) => listAnalysisCallNodes(props.taskId, aid, null, null, p.cursor, p.limit),
  { limit: 100, cursor: true },
);
const {
  items: callNodeItems,
  total: callNodeTotal,
  hasMore: callNodeHasMore,
  loading: callNodeLoading,
} = callNodesList;
function loadCallNodes(): void {
  const aid = analysisId.value;
  if (aid) void callNodesList.load(aid);
}
function loadMoreCallNodes(): void {
  const aid = analysisId.value;
  if (aid) void callNodesList.loadMore(aid);
}

const flowsList = usePagedList<ExecutionFlowInfo, [string]>(
  (p, aid) => listAnalysisExecutionFlows(props.taskId, aid, p.cursor, p.limit),
  { limit: 50, cursor: true },
);
const { items: flowItems, hasMore: flowHasMore, loading: flowLoading } = flowsList;
function loadFlows(): void {
  const aid = analysisId.value;
  if (aid) void flowsList.load(aid);
}
function loadMoreFlows(): void {
  const aid = analysisId.value;
  if (aid) void flowsList.loadMore(aid);
}

const findingsList = usePagedList<FindingInfo, [string]>(
  (p, aid) => listAnalysisFindings(props.taskId, aid, p.cursor, p.limit),
  { limit: 50, cursor: true },
);
const {
  items: findingItems,
  total: findingTotal,
  hasMore: findingHasMore,
  loading: findingLoading,
} = findingsList;
function loadFindings(): void {
  const aid = analysisId.value;
  if (aid) void findingsList.load(aid);
}
function loadMoreFindings(): void {
  const aid = analysisId.value;
  if (aid) void findingsList.loadMore(aid);
}

const clustersList = usePagedList<ClusterInfo, [string]>(
  (p, aid) => listAnalysisClusters(props.taskId, aid, p.cursor, p.limit),
  { limit: 50, cursor: true },
);
const {
  items: clusterItems,
  total: clusterTotal,
  hasMore: clusterHasMore,
  loading: clusterLoading,
} = clustersList;
function loadClusters(): void {
  const aid = analysisId.value;
  if (aid) void clustersList.load(aid);
}
function loadMoreClusters(): void {
  const aid = analysisId.value;
  if (aid) void clustersList.loadMore(aid);
}

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
    return;
  }
  selectedCallNodeId.value = nodeId;
  calleeItems.value = [];
  calleeLoading.value = true;
  try {
    const page = await listAnalysisCallEdges(props.taskId, aid, nodeId, null, 50);
    if (selectedCallNodeId.value === nodeId) {
      calleeItems.value = page.items;
    }
  } finally {
    if (selectedCallNodeId.value === nodeId) {
      calleeLoading.value = false;
    }
  }
}

// Diagnostics（非分页，tab 切换时懒加载一次）
const diagnostics = ref<DiagnosticsInfo | null>(null);
let diagLoaded = false;

async function loadDiagnostics(): Promise<void> {
  const aid = analysisId.value;
  if (!aid || diagLoaded) return;
  try {
    diagnostics.value = await getAnalysisDiagnostics(props.taskId, aid);
    diagLoaded = true;
  } catch (caught) {
    // 诊断为尽力而为展示，失败不阻塞页面，仅记录便于排查。
    console.warn("[WhiteboxReport] 诊断信息加载失败：", errorMessage(caught));
  }
}

function resetSubResources(): void {
  endpointsList.reset();
  callNodesList.reset();
  flowsList.reset();
  findingsList.reset();
  clustersList.reset();
  diagnostics.value = null;
  diagLoaded = false;
  selectedCallNodeId.value = null;
  calleeItems.value = [];
  calleeLoading.value = false;
}

/** 按当前激活的 tab 懒加载对应子资源。
 *
 * 以「列表为空才加载」作为门控：既保证 B2（切 run / 首次打开 tab 才拉取），
 * 又避免切回已加载过的 tab 时重置分页/滚动状态（只对空列表发请求）。
 * 加载失败时列表保持为空，下次切回会自动重试。
 */
function loadCurrentTabResources(): void {
  if (!analysisId.value) return;
  if (subTab.value === "endpoints" && endpointItems.value.length === 0) loadEndpoints();
  if (subTab.value === "callgraph" && callNodeItems.value.length === 0) loadCallNodes();
  if (subTab.value === "flows" && flowItems.value.length === 0) loadFlows();
  if (subTab.value === "diagnostics") loadDiagnostics();
  if (subTab.value === "findings" && findingItems.value.length === 0) loadFindings();
  if (subTab.value === "clusters" && clusterItems.value.length === 0) loadClusters();
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
  box-shadow: var(--shadow-sm);
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
  margin: 14px 0;
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
  box-shadow: var(--shadow-xs);
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
