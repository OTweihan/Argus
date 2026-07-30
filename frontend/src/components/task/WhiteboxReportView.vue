<template>
  <div v-loading="loading" class="wb-report">
    <template v-if="error">
      <el-empty :description="error || '加载失败'" />
    </template>
    <template v-else-if="summary">
      <AnalysisRunSelector
        :runs="runs"
        :selected-id="analysisId"
        :loading="loading"
        @select="onSelectRun"
      />

      <AnalysisSnapshotBar :summary="summary" />
      <CompletenessBanner :summary="summary" />

      <el-tabs v-model="subTab" type="border-card">
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
  DiagnosticsInfo,
  EndpointInfo,
  ExecutionFlowInfo,
} from "../../api/task";
import {
  getAnalysisDiagnostics,
  getAnalysisRunSummary,
  listAnalysisCallEdges,
  listAnalysisCallNodes,
  listAnalysisEndpoints,
  listAnalysisExecutionFlows,
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

const props = defineProps<{ taskId: string }>();

const summary = ref<AnalysisRunSummary | null>(null);
const runs = ref<AnalysisRunSummary[]>([]);
const analysisId = ref<string | null>(null);
const loading = ref(false);
const error = ref("");
const subTab = ref("overview");

// 初始化：加载历史列表 + 默认选择最新
(async () => {
  loading.value = true;
  try {
    const page = await listAnalysisRuns(props.taskId);
    runs.value = page.items;
    if (page.items.length > 0) {
      // 默认选择：RUNNING > SUCCEEDED > 最新
      const running = page.items.find((r: AnalysisRunSummary) => r.runStatus === "RUNNING");
      const succeeded = page.items.find((r: AnalysisRunSummary) => r.runStatus === "SUCCEEDED");
      const selected = running || succeeded || page.items[0];
      analysisId.value = selected.analysisId;
      summary.value = selected;
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
  // 从 runs 中查找，无需再请求 summary 接口
  const found = runs.value.find((r: AnalysisRunSummary) => r.analysisId === aid);
  if (found) {
    summary.value = found;
    return;
  }
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
    return;
  }
  selectedCallNodeId.value = nodeId;
  calleeLoading.value = true;
  try {
    const page = await listAnalysisCallEdges(props.taskId, analysisId.value, nodeId, null, 50);
    calleeItems.value = page.items;
  } finally {
    calleeLoading.value = false;
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
  diagnostics.value = null;
  selectedCallNodeId.value = null;
  diagLoaded = false;
  endpointCursor = null;
  callNodeCursor = null;
  flowCursor = null;
}

// Watch analysisId → load sub-resources
watch(analysisId, (aid) => {
  if (!aid) return;
  loadEndpoints();
  loadCallNodes();
  loadFlows();
});

// Watch subTab → lazy load diagnostics
watch(subTab, (tab) => {
  if (tab === "diagnostics") loadDiagnostics();
});
</script>

<style scoped>
.wb-report {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px;
}
</style>
