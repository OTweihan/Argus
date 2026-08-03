<template>
  <div v-loading="loading" class="corr-container">
    <template v-if="error">
      <el-empty :description="error" />
    </template>

    <template v-else-if="summary">
      <!-- 状态横幅 -->
      <div :class="['status-bar', `status-${runStatus}`]">
        <span class="status-label">{{ statusLabel }}</span>
        <span v-if="sourceAlignment" class="status-alignment">
          源码版本：{{ alignmentLabel }}
        </span>
        <span v-if="matcherVersion" class="status-version">
          matcher {{ matcherVersion }} / norm {{ normalizationVersion }}
        </span>
      </div>

      <el-tabs v-model="subTab" type="border-card">
        <!-- 关联总览 -->
        <el-tab-pane lazy label="关联总览" name="overview">
          <div class="overview-grid">
            <!-- 请求级 -->
            <div class="card">
              <div class="card-title">
                请求证据
              </div>
              <div class="stat-row">
                <span class="stat-k">采集总数</span>
                <span class="stat-v">{{ summary.capturedRequestCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">可关联</span>
                <span class="stat-v">{{ summary.correlatableRequestCount }}</span>
              </div>
              <div class="stat-row confirmed">
                <span class="stat-k">已确认命中</span>
                <span class="stat-v">{{ summary.confirmedMatchedRequestCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">歧义</span>
                <span class="stat-v">{{ summary.ambiguousRequestCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">方法不一致候选</span>
                <span class="stat-v">{{ summary.methodMismatchCandidateCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">未匹配</span>
                <span class="stat-v">{{ summary.unmatchedRequestCount }}</span>
              </div>
            </div>

            <!-- 端点级 -->
            <div class="card">
              <div class="card-title">
                端点覆盖
              </div>
              <div class="stat-row">
                <span class="stat-k">白盒端点总数</span><span class="stat-v">{{ summary.totalEndpointCount }}</span>
              </div>
              <div class="stat-row confirmed">
                <span class="stat-k">已确认触达</span><span class="stat-v">{{ summary.confirmedTouchedEndpointCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">候选触达</span><span class="stat-v">{{ summary.candidateTouchedEndpointCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">尝试触达</span><span class="stat-v">{{ summary.attemptedEvidenceCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">未触达</span><span class="stat-v">{{ summary.uncoveredEndpointCount }}</span>
              </div>
              <div v-if="summary.totalEndpointCount > 0" class="stat-row">
                <span class="stat-k">触达率</span>
                <span class="stat-v">{{ coveragePercent }}%</span>
              </div>
            </div>

            <!-- Finding 级 -->
            <div class="card">
              <div class="card-title">
                发现项关联
              </div>
              <div class="stat-row">
                <span class="stat-k">白盒发现项</span><span class="stat-v">{{ summary.totalFindingCount }}</span>
              </div>
              <div class="stat-row confirmed">
                <span class="stat-k">已确认关联</span><span class="stat-v">{{ summary.confirmedRelatedFindingCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">候选关联</span><span class="stat-v">{{ summary.candidateRelatedFindingCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">未关联</span><span class="stat-v">{{ summary.unrelatedFindingCount }}</span>
              </div>
            </div>

            <!-- 采集质量 -->
            <div class="card">
              <div class="card-title">
                采集质量
              </div>
              <div class="stat-row">
                <span class="stat-k">跨域过滤</span><span class="stat-v">{{ summary.crossOriginFilteredCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">资源类型过滤</span><span class="stat-v">{{ summary.resourceFilteredCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">丢弃</span><span class="stat-v">{{ summary.droppedRequestCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">采集失败</span><span class="stat-v">{{ summary.failedCaptureCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">完整性</span>
                <el-tag size="small" :type="completenessTag">
                  {{ summary.evidenceCompleteness }}
                </el-tag>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- 命中端点 -->
        <el-tab-pane lazy label="命中端点" name="endpoints">
          <EndpointEvidenceTable
            :items="evidenceItems"
            :total="evidenceTotal"
            :has-more="evidenceHasMore"
            :loading="evidenceLoading"
            :status-filter="evidenceFilter"
            @load-more="loadMoreEvidence"
            @filter-change="onEvidenceFilterChange"
          />
        </el-tab-pane>

        <!-- 发现关联 -->
        <el-tab-pane lazy label="发现关联" name="findings">
          <FindingEvidenceTable
            :items="findingEvItems"
            :total="findingEvTotal"
            :has-more="findingEvHasMore"
            :loading="findingEvLoading"
            @load-more="loadMoreFindingEvidence"
          />
        </el-tab-pane>

        <!-- 未触达端点 -->
        <el-tab-pane lazy label="未触达端点" name="uncovered">
          <div class="list-wrap">
            <el-empty v-if="!summary.uncoveredEndpointCount" description="所有白盒端点均已触达" />
            <template v-else>
              <div class="list-toolbar">
                <span class="list-count">共 {{ uncoveredTotal ?? summary.uncoveredEndpointCount }} 个端点未触达</span>
              </div>
              <el-table :data="uncoveredItems" size="small" stripe style="width:100%" max-height="400">
                <el-table-column label="方法" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" :type="httpMethodTag(row.httpMethod)">
                      {{ row.httpMethod }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="路径" min-width="200">
                  <template #default="{ row }">
                    <span class="mano">{{ row.normalizedPathTemplate || row.normalizedPath }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="控制器" min-width="200">
                  <template #default="{ row }">
                    <span v-if="row.controllerClass || row.controllerMethod" class="mano">
                      {{ row.controllerClass }}.{{ row.controllerMethod }}
                    </span>
                    <span v-else class="text-faint">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="路径段数" width="90">
                  <template #default="{ row }">
                    {{ row.pathSegmentCount }}
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="uncoveredHasMore" class="list-more">
                <el-button size="small" :loading="uncoveredLoading" @click="loadMoreUncovered">
                  加载更多
                </el-button>
              </div>
            </template>
          </div>
        </el-tab-pane>

        <!-- 未匹配请求 -->
        <el-tab-pane lazy label="未匹配请求" name="unmatched">
          <UnmatchedRequestTable
            :items="unmatchedItems"
            :total="unmatchedTotal"
            :has-more="unmatchedHasMore"
            :loading="unmatchedLoading"
            @load-more="loadMoreUnmatched"
          />
        </el-tab-pane>

        <!-- 数据质量 -->
        <el-tab-pane lazy label="数据质量" name="quality">
          <div v-if="captureQuality" class="quality-section">
            <div class="card">
              <div class="card-title">
                采集详细统计
              </div>
              <div class="stat-row">
                <span class="stat-k">观察总数</span>
                <span class="stat-v">{{ captureQuality.totalObserved }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">接受并采集</span>
                <span class="stat-v">{{ captureQuality.acceptedStarted }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">已持久化</span>
                <span class="stat-v">{{ captureQuality.persistedCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">跨域过滤</span>
                <span class="stat-v">{{ captureQuality.filteredCrossOrigin }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">资源类型过滤</span>
                <span class="stat-v">{{ captureQuality.filteredByResourceType }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">方法过滤</span>
                <span class="stat-v">{{ captureQuality.filteredByMethod }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">WebSocket 过滤</span>
                <span class="stat-v">{{ captureQuality.filteredWebsocketCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">路径超长过滤</span>
                <span class="stat-v">{{ captureQuality.filteredPathTooLong }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">Pending 满丢弃</span>
                <span class="stat-v">{{ captureQuality.droppedPendingLimit }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">Run 上限丢弃</span>
                <span class="stat-v">{{ captureQuality.droppedRunLimit }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">Writer 队列满丢弃</span>
                <span class="stat-v">{{ captureQuality.droppedWriterQueueLimit }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">Writer 重试次数</span>
                <span class="stat-v">{{ captureQuality.writerRetryCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">Writer 失败批次</span>
                <span class="stat-v">{{ captureQuality.writerFailedBatchCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">持久化失败</span>
                <span class="stat-v">{{ captureQuality.persistenceFailed }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-k">截断</span>
                <el-tag size="small" :type="captureQuality.truncated ? 'danger' : 'success'">
                  {{ captureQuality.truncated ? '是' : '否' }}
                </el-tag>
                <span v-if="captureQuality.truncationReason" class="trunc-reason">{{ captureQuality.truncationReason }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无采集质量数据" />
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-empty v-else description="暂无关联运行数据" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  getCorrelationSummary,
  getCaptureQuality,
  listEndpointEvidence,
  listFindingEvidence,
  listUnmatchedRequests,
  listUncoveredEndpoints,
  type CorrelationSummaryInfo,
  type CaptureQualityInfo,
  type EndpointEvidenceInfo,
  type FindingEvidenceInfo,
  type HttpRequestEvidenceInfo,
  type UncoveredEndpointInfo,
} from "../../../api/correlation";
import { errorMessage, httpMethodTag } from "../../../utils";
import EndpointEvidenceTable from "./correlation/EndpointEvidenceTable.vue";
import FindingEvidenceTable from "./correlation/FindingEvidenceTable.vue";
import UnmatchedRequestTable from "./correlation/UnmatchedRequestTable.vue";

const props = defineProps<{ correlationRunId: string }>();

const summary = ref<CorrelationSummaryInfo | null>(null);
const captureQuality = ref<CaptureQualityInfo | null>(null);
const loading = ref(false);
const error = ref("");
const subTab = ref("overview");

// ── 初始化 ──

(async () => {
  loading.value = true;
  try {
    const [s, q] = await Promise.all([
      getCorrelationSummary(props.correlationRunId),
      getCaptureQuality(props.correlationRunId).catch(() => null),
    ]);
    summary.value = s;
    captureQuality.value = q;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
})();

// ── 状态展示 ──

const runStatus = computed(() => summary.value?.status ?? "");
const sourceAlignment = computed(() => summary.value?.sourceAlignmentStatus ?? "");
const matcherVersion = computed(() => summary.value?.matcherVersion ?? "");
const normalizationVersion = computed(() => summary.value?.normalizationVersion ?? "");

const statusLabels: Record<string, string> = {
  WAITING_ANALYSIS: "等待白盒分析",
  WAITING_BINDING: "等待用户绑定",
  WAITING_BLACKBOX: "等待黑盒执行",
  BLOCKED: "已阻止",
  READY: "就绪",
  RUNNING: "关联中",
  SUCCEEDED: "关联成功",
  PARTIAL: "部分完成",
  FAILED: "关联失败",
  STALE: "已过期",
};

const statusLabel = computed(() => statusLabels[runStatus.value] ?? runStatus.value);

const alignmentLabels: Record<string, string> = {
  VERIFIED: "已验证",
  USER_DECLARED: "用户声明",
  UNVERIFIED: "未验证",
  MISMATCHED: "不一致",
};

const alignmentLabel = computed(() => alignmentLabels[sourceAlignment.value] ?? sourceAlignment.value);

const coveragePercent = computed(() => {
  if (!summary.value || summary.value.totalEndpointCount === 0) return 0;
  return Math.round(
    (summary.value.confirmedTouchedEndpointCount / summary.value.totalEndpointCount) * 100,
  );
});

const completenessTag = computed(() => {
  return summary.value?.evidenceCompleteness === "COMPLETE" ? "success" : "warning";
});

// ── 端点证据分页 ──

const evidenceItems = ref<EndpointEvidenceInfo[]>([]);
const evidenceTotal = ref<number | null>(null);
const evidenceHasMore = ref(false);
const evidenceLoading = ref(false);
const evidenceFilter = ref("");

async function loadEvidence(): Promise<void> {
  evidenceLoading.value = true;
  try {
    const page = await listEndpointEvidence(props.correlationRunId, {
      resolutionStatus: evidenceFilter.value || undefined,
      offset: 0,
      limit: 100,
    });
    evidenceItems.value = page.items;
    evidenceTotal.value = page.total;
    evidenceHasMore.value = page.hasMore;
  } finally {
    evidenceLoading.value = false;
  }
}

async function loadMoreEvidence(): Promise<void> {
  evidenceLoading.value = true;
  try {
    const page = await listEndpointEvidence(props.correlationRunId, {
      resolutionStatus: evidenceFilter.value || undefined,
      offset: evidenceItems.value.length,
      limit: 100,
    });
    evidenceItems.value.push(...page.items);
    evidenceHasMore.value = page.hasMore;
  } finally {
    evidenceLoading.value = false;
  }
}

function onEvidenceFilterChange(status: string): void {
  evidenceFilter.value = status;
  loadEvidence();
}

// ── Finding 证据分页 ──

const findingEvItems = ref<FindingEvidenceInfo[]>([]);
const findingEvTotal = ref<number | null>(null);
const findingEvHasMore = ref(false);
const findingEvLoading = ref(false);

async function loadFindingEvidence(): Promise<void> {
  findingEvLoading.value = true;
  try {
    const page = await listFindingEvidence(props.correlationRunId, 0, 100);
    findingEvItems.value = page.items;
    findingEvTotal.value = page.total;
    findingEvHasMore.value = page.hasMore;
  } finally {
    findingEvLoading.value = false;
  }
}

async function loadMoreFindingEvidence(): Promise<void> {
  findingEvLoading.value = true;
  try {
    const page = await listFindingEvidence(
      props.correlationRunId,
      findingEvItems.value.length,
      100,
    );
    findingEvItems.value.push(...page.items);
    findingEvHasMore.value = page.hasMore;
  } finally {
    findingEvLoading.value = false;
  }
}

// ── 未匹配请求分页 ──

const unmatchedItems = ref<HttpRequestEvidenceInfo[]>([]);
const unmatchedTotal = ref<number | null>(null);
const unmatchedHasMore = ref(false);
const unmatchedLoading = ref(false);

async function loadUnmatched(): Promise<void> {
  unmatchedLoading.value = true;
  try {
    const page = await listUnmatchedRequests(props.correlationRunId, 0, 100);
    unmatchedItems.value = page.items;
    unmatchedTotal.value = page.total;
    unmatchedHasMore.value = page.hasMore;
  } finally {
    unmatchedLoading.value = false;
  }
}

async function loadMoreUnmatched(): Promise<void> {
  unmatchedLoading.value = true;
  try {
    const page = await listUnmatchedRequests(
      props.correlationRunId,
      unmatchedItems.value.length,
      100,
    );
    unmatchedItems.value.push(...page.items);
    unmatchedHasMore.value = page.hasMore;
  } finally {
    unmatchedLoading.value = false;
  }
}

// ── 未触达端点分页 ──

const uncoveredItems = ref<UncoveredEndpointInfo[]>([]);
const uncoveredTotal = ref<number | null>(null);
const uncoveredHasMore = ref(false);
const uncoveredLoading = ref(false);

async function loadUncovered(): Promise<void> {
  if (uncoveredItems.value.length > 0) return; // 懒加载一次
  uncoveredLoading.value = true;
  try {
    const page = await listUncoveredEndpoints(props.correlationRunId, 0, 100);
    uncoveredItems.value = page.items;
    uncoveredTotal.value = page.total;
    uncoveredHasMore.value = page.hasMore;
  } finally {
    uncoveredLoading.value = false;
  }
}

async function loadMoreUncovered(): Promise<void> {
  uncoveredLoading.value = true;
  try {
    const page = await listUncoveredEndpoints(
      props.correlationRunId,
      uncoveredItems.value.length,
      100,
    );
    uncoveredItems.value.push(...page.items);
    uncoveredHasMore.value = page.hasMore;
  } finally {
    uncoveredLoading.value = false;
  }
}

// ── Tab 懒加载 ──

watch(subTab, (tab) => {
  if (tab === "endpoints") loadEvidence();
  if (tab === "findings") loadFindingEvidence();
  if (tab === "unmatched") loadUnmatched();
  if (tab === "uncovered") loadUncovered();
});
</script>

<style scoped>
.corr-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px;
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 14px;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}

.status-SUCCEEDED { background: #ecfdf5; border: 1px solid #a7f3d0; }
.status-FAILED    { background: #fef2f2; border: 1px solid #fecaca; }
.status-RUNNING   { background: #eff6ff; border: 1px solid #bfdbfe; }
.status-PARTIAL   { background: #fffbeb; border: 1px solid #fde68a; }
.status-STALE     { background: #f3f4f6; border: 1px solid #d1d5db; }
.status-READY     { background: #f0fdf4; border: 1px solid #bbf7d0; }

.status-label {
  font-weight: 700;
}

.status-alignment {
  color: var(--text-faint);
  font-size: 12px;
}

.status-version {
  color: var(--text-faint);
  font-size: 11px;
  margin-left: auto;
}

/* 总览网格 */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  padding: 4px 0;
}

.card {
  background: var(--surface-soft, #f9fafb);
  border: 1px solid var(--line-soft, #e5e7eb);
  border-radius: 8px;
  padding: 12px 14px;
}

.card-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-strong);
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line-soft, #e5e7eb);
}

.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 13px;
}

.stat-k {
  color: var(--text-faint);
}

.stat-v {
  font-weight: 600;
  color: var(--text-strong);
}

.stat-row.confirmed .stat-v {
  color: #059669;
}

.quality-section {
  padding: 4px 0;
}

.trunc-reason {
  font-size: 12px;
  color: var(--text-faint);
  margin-left: 8px;
}

.list-wrap {
  padding: 4px 0;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.list-count {
  font-size: 12px;
  color: var(--text-faint);
}

.list-more {
  margin-top: 8px;
  text-align: center;
}

.mano {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
</style>
