<template>
  <div v-loading="loading" class="wb-report">
    <template v-if="error">
      <el-empty :description="error || '加载失败'" />
    </template>
    <template v-else-if="summary">
      <section class="report-hero" aria-labelledby="whitebox-report-title">
        <div class="hero-copy">
          <span class="hero-kicker">WHITEBOX ANALYSIS</span>
          <h2 id="whitebox-report-title">
            白盒分析报告
          </h2>
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
        <el-tab-pane lazy label="诊断" name="diagnostics">
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
    </template>
    <el-empty v-else description="暂无分析执行数据，请先启动白盒任务" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
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
  analysisId.value = aid;
  resetSubResources();
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

// ── 分页子资源 ──

// Endpoints
const endpointItems = ref<EndpointInfo[]>([]);
const endpointTotal = ref<number | null>(null);
const endpointHasMore = ref(false);
const endpointLoading = ref(false);
let endpointCursor: string | null = null;

async function loadEndpoints(): Promise<void> {
  if (!analysisId.value) return;
  endpointLoading.value = true;
  try {
    const page = await listAnalysisEndpoints(props.taskId, analysisId.value, null, 100);
    endpointItems.value = page.items;
    endpointTotal.value = page.total ?? null;
    endpointHasMore.value = page.hasMore;
    endpointCursor = page.nextCursor ?? null;
  } finally {
    endpointLoading.value = false;
  }
}

async function loadMoreEndpoints(): Promise<void> {
  if (!analysisId.value || !endpointCursor) return;
  endpointLoading.value = true;
  try {
    const page = await listAnalysisEndpoints(props.taskId, analysisId.value, endpointCursor, 100);
    endpointItems.value.push(...page.items);
    endpointHasMore.value = page.hasMore;
    endpointCursor = page.nextCursor ?? null;
  } finally {
    endpointLoading.value = false;
  }
}

// CallNodes
const callNodeItems = ref<CallNodeInfo[]>([]);
const callNodeTotal = ref<number | null>(null);
const callNodeHasMore = ref(false);
const callNodeLoading = ref(false);
let callNodeCursor: string | null = null;

async function loadCallNodes(): Promise<void> {
  if (!analysisId.value) return;
  callNodeLoading.value = true;
  try {
    const page = await listAnalysisCallNodes(props.taskId, analysisId.value, null, null, null, 100);
    callNodeItems.value = page.items;
    callNodeTotal.value = page.total ?? null;
    callNodeHasMore.value = page.hasMore;
    callNodeCursor = page.nextCursor ?? null;
  } finally {
    callNodeLoading.value = false;
  }
}

async function loadMoreCallNodes(): Promise<void> {
  if (!analysisId.value || !callNodeCursor) return;
  callNodeLoading.value = true;
  try {
    const page = await listAnalysisCallNodes(props.taskId, analysisId.value, null, null, callNodeCursor, 100);
    callNodeItems.value.push(...page.items);
    callNodeHasMore.value = page.hasMore;
    callNodeCursor = page.nextCursor ?? null;
  } finally {
    callNodeLoading.value = false;
  }
}

// Callee edges (per selected node)
const selectedCallNodeId = ref<string | null>(null);
const calleeItems = ref<CallEdgeInfo[]>([]);
const calleeLoading = ref(false);

async function selectCallNode(nodeId: string): Promise<void> {
  if (!analysisId.value) return;
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
    const page = await listAnalysisCallEdges(props.taskId, analysisId.value, nodeId, null, 50);
    if (selectedCallNodeId.value === nodeId) {
      calleeItems.value = page.items;
    }
  } finally {
    if (selectedCallNodeId.value === nodeId) {
      calleeLoading.value = false;
    }
  }
}

// ExecutionFlows
const flowItems = ref<ExecutionFlowInfo[]>([]);
const flowHasMore = ref(false);
const flowLoading = ref(false);
let flowCursor: string | null = null;

async function loadFlows(): Promise<void> {
  if (!analysisId.value) return;
  flowLoading.value = true;
  try {
    const page = await listAnalysisExecutionFlows(props.taskId, analysisId.value, null, 50);
    flowItems.value = page.items;
    flowHasMore.value = page.hasMore;
    flowCursor = page.nextCursor ?? null;
  } finally {
    flowLoading.value = false;
  }
}

async function loadMoreFlows(): Promise<void> {
  if (!analysisId.value || !flowCursor) return;
  flowLoading.value = true;
  try {
    const page = await listAnalysisExecutionFlows(props.taskId, analysisId.value, flowCursor, 50);
    flowItems.value.push(...page.items);
    flowHasMore.value = page.hasMore;
    flowCursor = page.nextCursor ?? null;
  } finally {
    flowLoading.value = false;
  }
}

// Diagnostics (loaded on tab switch)
const diagnostics = ref<DiagnosticsInfo | null>(null);
let diagLoaded = false;

async function loadDiagnostics(): Promise<void> {
  if (!analysisId.value || diagLoaded) return;
  try {
    diagnostics.value = await getAnalysisDiagnostics(props.taskId, analysisId.value);
    diagLoaded = true;
  } catch {
    // ignore
  }
}

function resetSubResources(): void {
  endpointItems.value = [];
  callNodeItems.value = [];
  calleeItems.value = [];
  flowItems.value = [];
  findingItems.value = [];
  clusterItems.value = [];
  diagnostics.value = null;
  selectedCallNodeId.value = null;
  diagLoaded = false;
  endpointCursor = null;
  callNodeCursor = null;
  flowCursor = null;
  findingCursor = null;
  clusterCursor = null;
}

// Findings
const findingItems = ref<FindingInfo[]>([]);
const findingTotal = ref<number | null>(null);
const findingHasMore = ref(false);
const findingLoading = ref(false);
let findingCursor: string | null = null;

async function loadFindings(): Promise<void> {
  if (!analysisId.value) return;
  findingLoading.value = true;
  try {
    const page = await listAnalysisFindings(props.taskId, analysisId.value, null, 50);
    findingItems.value = page.items;
    findingTotal.value = page.total ?? null;
    findingHasMore.value = page.hasMore;
    findingCursor = page.nextCursor ?? null;
  } finally {
    findingLoading.value = false;
  }
}

async function loadMoreFindings(): Promise<void> {
  if (!analysisId.value || !findingCursor) return;
  findingLoading.value = true;
  try {
    const page = await listAnalysisFindings(props.taskId, analysisId.value, findingCursor, 50);
    findingItems.value.push(...page.items);
    findingHasMore.value = page.hasMore;
    findingCursor = page.nextCursor ?? null;
  } finally {
    findingLoading.value = false;
  }
}

// Clusters (lazy load on tab switch)
const clusterItems = ref<ClusterInfo[]>([]);
const clusterTotal = ref<number | null>(null);
const clusterHasMore = ref(false);
const clusterLoading = ref(false);
let clusterCursor: string | null = null;

async function loadClusters(): Promise<void> {
  if (!analysisId.value) return;
  clusterLoading.value = true;
  try {
    const page = await listAnalysisClusters(props.taskId, analysisId.value, null, 50);
    clusterItems.value = page.items;
    clusterTotal.value = page.total ?? null;
    clusterHasMore.value = page.hasMore;
    clusterCursor = page.nextCursor ?? null;
  } finally {
    clusterLoading.value = false;
  }
}

async function loadMoreClusters(): Promise<void> {
  if (!analysisId.value || !clusterCursor) return;
  clusterLoading.value = true;
  try {
    const page = await listAnalysisClusters(props.taskId, analysisId.value, clusterCursor, 50);
    clusterItems.value.push(...page.items);
    clusterHasMore.value = page.hasMore;
    clusterCursor = page.nextCursor ?? null;
  } finally {
    clusterLoading.value = false;
  }
}

// Watch analysisId → load sub-resources
watch(analysisId, (aid) => {
  if (!aid) return;
  loadEndpoints();
  loadCallNodes();
  loadFlows();
  // 若当前已停留在诊断/发现项/聚类 Tab，切换 run 时同步刷新
  if (subTab.value === "diagnostics") loadDiagnostics();
  if (subTab.value === "findings") loadFindings();
  if (subTab.value === "clusters") loadClusters();
});

// Watch subTab → lazy load diagnostics / findings / clusters
watch(subTab, (tab) => {
  if (tab === "diagnostics") loadDiagnostics();
  if (tab === "findings") loadFindings();
  if (tab === "clusters") loadClusters();
});
</script>

<style scoped>
.wb-report {
  flex: 1;
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
  grid-template-columns: minmax(0, 1.65fr) minmax(280px, 0.8fr);
  gap: 12px;
  margin: 14px 0;
}

.report-tabs {
  padding: 0 16px 16px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-xs);
}

.report-tabs :deep(.el-tabs__header) {
  margin: 0 -16px 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line-soft);
  background: rgba(248, 250, 252, 0.78);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
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
  box-shadow: 0 0 0 1px var(--brand-500) inset, var(--shadow-ring);
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
