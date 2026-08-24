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
            <StatCard
              v-for="card in overviewCards"
              :key="card.title"
              :title="card.title"
              :items="card.items"
            />
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
                <span class="list-count"
                  >共 {{ uncoveredTotal ?? summary.uncoveredEndpointCount }} 个端点未触达</span
                >
              </div>
              <el-table :data="uncoveredItems" size="small" stripe style="width: 100%">
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
                <template #append>
                  <InfiniteScrollLoad
                    :has-more="uncoveredHasMore"
                    :loading="uncoveredLoading"
                    @load-more="loadMoreUncovered"
                  />
                </template>
              </el-table>
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
            <StatCard
              v-for="card in qualityCards"
              :key="card.title"
              :title="card.title"
              :items="card.items"
            />
          </div>
          <el-empty v-else description="暂无采集质量数据" />
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-empty v-else description="暂无关联运行数据" />
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
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
import { usePagedList } from "../../../composables/usePagedList";
import EndpointEvidenceTable from "./correlation/EndpointEvidenceTable.vue";
import FindingEvidenceTable from "./correlation/FindingEvidenceTable.vue";
import UnmatchedRequestTable from "./correlation/UnmatchedRequestTable.vue";
import InfiniteScrollLoad from "../../common/InfiniteScrollLoad.vue";
import StatCard, { type StatCardConfig } from "../../common/StatCard.vue";

const props = defineProps<{ correlationRunId: string }>();

const summary = ref<CorrelationSummaryInfo | null>(null);
const captureQuality = ref<CaptureQualityInfo | null>(null);
const loading = ref(false);
const error = ref("");
const subTab = ref("overview");

// ── 初始化 ──

// F7：首屏 IIFE 加 AbortController 守卫，组件卸载后中止在途请求，避免晚到响应
// 写入已卸载组件。
let initialLoadAbort: AbortController | null = null;
(async () => {
  const controller = new AbortController();
  initialLoadAbort = controller;
  loading.value = true;
  try {
    const [s, q] = await Promise.all([
      getCorrelationSummary(props.correlationRunId, { signal: controller.signal }),
      getCaptureQuality(props.correlationRunId, { signal: controller.signal }).catch(() => null),
    ]);
    if (controller.signal.aborted) return;
    summary.value = s;
    captureQuality.value = q;
  } catch (e) {
    if (!controller.signal.aborted) error.value = errorMessage(e);
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
})();

onUnmounted(() => {
  initialLoadAbort?.abort();
});

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

const alignmentLabel = computed(
  () => alignmentLabels[sourceAlignment.value] ?? sourceAlignment.value,
);

const coveragePercent = computed(() => {
  if (!summary.value || summary.value.totalEndpointCount === 0) return 0;
  return Math.round(
    (summary.value.confirmedTouchedEndpointCount / summary.value.totalEndpointCount) * 100,
  );
});

const completenessTag = computed(() => {
  return summary.value?.evidenceCompleteness === "COMPLETE" ? "success" : "warning";
});

// ── 总览 / 数据质量卡片（F3-4：数据驱动 StatCard，替代手写 stat 行模板） ──

const overviewCards = computed<StatCardConfig[]>(() => {
  const s = summary.value;
  if (!s) return [];
  return [
    {
      title: "请求证据",
      items: [
        { key: "captured", label: "采集总数", value: s.capturedRequestCount },
        { key: "correlatable", label: "可关联", value: s.correlatableRequestCount },
        {
          key: "confirmedMatched",
          label: "已确认命中",
          value: s.confirmedMatchedRequestCount,
          confirmed: true,
        },
        { key: "ambiguous", label: "歧义", value: s.ambiguousRequestCount },
        {
          key: "methodMismatch",
          label: "方法不一致候选",
          value: s.methodMismatchCandidateCount,
        },
        { key: "unmatchedRequests", label: "未匹配", value: s.unmatchedRequestCount },
      ],
    },
    {
      title: "端点覆盖",
      items: [
        { key: "totalEndpoints", label: "白盒端点总数", value: s.totalEndpointCount },
        {
          key: "confirmedTouched",
          label: "已确认触达",
          value: s.confirmedTouchedEndpointCount,
          confirmed: true,
        },
        { key: "candidateTouched", label: "候选触达", value: s.candidateTouchedEndpointCount },
        { key: "attemptedEvidence", label: "尝试触达", value: s.attemptedEvidenceCount },
        { key: "uncoveredEndpoints", label: "未触达", value: s.uncoveredEndpointCount },
        {
          key: "coverage",
          label: "触达率",
          value: coveragePercent.value,
          suffix: "%",
          show: s.totalEndpointCount > 0,
        },
      ],
    },
    {
      title: "发现项关联",
      items: [
        { key: "totalFindings", label: "白盒发现项", value: s.totalFindingCount },
        {
          key: "confirmedRelated",
          label: "已确认关联",
          value: s.confirmedRelatedFindingCount,
          confirmed: true,
          hint: "被黑盒实际触达（confirmed_request_count > 0）的发现项",
        },
        {
          key: "candidateRelated",
          label: "候选关联",
          value: s.candidateRelatedFindingCount,
          hint: "有静态关联但未被黑盒请求触达的发现项",
        },
        {
          key: "unrelatedFindings",
          label: "未关联",
          value: s.unrelatedFindingCount,
          hint: "无任何关联证据的发现项",
        },
      ],
    },
    {
      title: "采集质量",
      items: [
        { key: "crossOriginFiltered", label: "跨域过滤", value: s.crossOriginFilteredCount },
        { key: "resourceFiltered", label: "资源类型过滤", value: s.resourceFilteredCount },
        { key: "droppedRequests", label: "丢弃", value: s.droppedRequestCount },
        { key: "failedCapture", label: "采集失败", value: s.failedCaptureCount },
        {
          key: "completeness",
          label: "完整性",
          tag: { type: completenessTag.value, text: s.evidenceCompleteness },
        },
      ],
    },
  ];
});

const qualityCards = computed<StatCardConfig[]>(() => {
  const q = captureQuality.value;
  if (!q) return [];
  return [
    {
      title: "采集详细统计",
      items: [
        { key: "totalObserved", label: "观察总数", value: q.totalObserved },
        { key: "acceptedStarted", label: "接受并采集", value: q.acceptedStarted },
        { key: "persisted", label: "已持久化", value: q.persistedCount },
        { key: "filteredCrossOrigin", label: "跨域过滤", value: q.filteredCrossOrigin },
        {
          key: "filteredByResourceType",
          label: "资源类型过滤",
          value: q.filteredByResourceType,
        },
        { key: "filteredByMethod", label: "方法过滤", value: q.filteredByMethod },
        {
          key: "filteredWebsocket",
          label: "WebSocket 过滤",
          value: q.filteredWebsocketCount,
        },
        { key: "filteredPathTooLong", label: "路径超长过滤", value: q.filteredPathTooLong },
        { key: "droppedPendingLimit", label: "Pending 满丢弃", value: q.droppedPendingLimit },
        { key: "droppedRunLimit", label: "Run 上限丢弃", value: q.droppedRunLimit },
        {
          key: "droppedWriterQueueLimit",
          label: "Writer 队列满丢弃",
          value: q.droppedWriterQueueLimit,
        },
        { key: "writerRetry", label: "Writer 重试次数", value: q.writerRetryCount },
        {
          key: "writerFailedBatch",
          label: "Writer 失败批次",
          value: q.writerFailedBatchCount,
        },
        { key: "persistenceFailed", label: "持久化失败", value: q.persistenceFailed },
        {
          key: "truncated",
          label: "截断",
          tag: { type: q.truncated ? "danger" : "success", text: q.truncated ? "是" : "否" },
          note: q.truncationReason || undefined,
        },
      ],
    },
  ];
});

// ── 端点证据分页 ──

const evidenceFilter = ref("");

const evidenceList = usePagedList<EndpointEvidenceInfo, []>(
  (p) =>
    listEndpointEvidence(props.correlationRunId, {
      resolutionStatus: evidenceFilter.value || undefined,
      offset: p.offset,
      limit: p.limit,
    }),
  { limit: 100 },
);
const {
  items: evidenceItems,
  total: evidenceTotal,
  hasMore: evidenceHasMore,
  loading: evidenceLoading,
} = evidenceList;
const loadMoreEvidence = (): void => void evidenceList.loadMore();

function onEvidenceFilterChange(status: string): void {
  evidenceFilter.value = status;
  void evidenceList.load();
}

// ── Finding 证据分页 ──

const findingEvList = usePagedList<FindingEvidenceInfo, []>(
  (p) => listFindingEvidence(props.correlationRunId, p.offset, p.limit),
  { limit: 100 },
);
const {
  items: findingEvItems,
  total: findingEvTotal,
  hasMore: findingEvHasMore,
  loading: findingEvLoading,
} = findingEvList;
const loadMoreFindingEvidence = (): void => void findingEvList.loadMore();

// ── 未匹配请求分页 ──

const unmatchedList = usePagedList<HttpRequestEvidenceInfo, []>(
  (p) => listUnmatchedRequests(props.correlationRunId, p.offset, p.limit),
  { limit: 100 },
);
const {
  items: unmatchedItems,
  total: unmatchedTotal,
  hasMore: unmatchedHasMore,
  loading: unmatchedLoading,
} = unmatchedList;
const loadMoreUnmatched = (): void => void unmatchedList.loadMore();

// ── 未触达端点分页 ──

const uncoveredList = usePagedList<UncoveredEndpointInfo, []>(
  (p) => listUncoveredEndpoints(props.correlationRunId, p.offset, p.limit),
  { limit: 100, lazyOnce: true },
);
const {
  items: uncoveredItems,
  total: uncoveredTotal,
  hasMore: uncoveredHasMore,
  loading: uncoveredLoading,
} = uncoveredList;
const loadMoreUncovered = (): void => void uncoveredList.loadMore();

// ── Tab 懒加载 ──
// 子表在切换 tab 后仍保持挂载（el-tabs 内部 pane 保留），items 跨切换保留；
// 仅在首次访问该页签（items 为空）时加载，避免每次切换重复拉第 1 页并丢弃
// 已加载分页。注意：evidenceList 不能用 lazyOnce（onEvidenceFilterChange 需显式
// 重载），因此用 items.length === 0 门。
watch(subTab, (tab) => {
  if (tab === "endpoints" && evidenceItems.value.length === 0) void evidenceList.load();
  if (tab === "findings" && findingEvItems.value.length === 0) void findingEvList.load();
  if (tab === "unmatched" && unmatchedItems.value.length === 0) void unmatchedList.load();
  if (tab === "uncovered" && uncoveredItems.value.length === 0) void uncoveredList.load();
});

</script>

<style scoped>
.corr-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 2px 0;
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  margin-bottom: 12px;
  font-size: 13px;
}

.status-SUCCEEDED {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}
.status-FAILED {
  background: #fef2f2;
  border: 1px solid #fecaca;
}
.status-RUNNING {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}
.status-PARTIAL {
  background: #fffbeb;
  border: 1px solid #fde68a;
}
.status-STALE {
  background: #f3f4f6;
  border: 1px solid #d1d5db;
}
.status-READY {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

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

.quality-section {
  padding: 4px 0;
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

.mano {
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 640px) {
  .status-bar,
  .list-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .status-version {
    margin-left: 0;
  }
}
</style>
