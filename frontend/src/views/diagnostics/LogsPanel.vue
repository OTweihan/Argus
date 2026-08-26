<template>
  <div class="logs-panel">
    <el-form inline class="filter-bar" @submit.prevent>
      <el-form-item label="组件">
        <el-select v-model="filters.component" style="width: 130px" @change="resetAndSearch">
          <el-option
            v-for="opt in COMPONENT_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="级别">
        <el-select v-model="filters.level" style="width: 120px" @change="resetAndSearch">
          <el-option
            v-for="opt in LEVEL_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="时间范围">
        <el-select v-model="timeRange" style="width: 130px" @change="resetAndSearch">
          <el-option value="all" label="全部时间" />
          <el-option value="1h" label="最近 1 小时" />
          <el-option value="24h" label="最近 24 小时" />
          <el-option value="7d" label="最近 7 天" />
        </el-select>
      </el-form-item>
      <el-form-item label="关键词">
        <el-input
          v-model="filters.keyword"
          placeholder="消息/模块/堆栈包含…"
          clearable
          style="width: 200px"
          @keyup.enter="resetAndSearch"
        />
      </el-form-item>
      <el-form-item label="Request ID">
        <el-input
          v-model="filters.requestId"
          placeholder="req_…"
          clearable
          style="width: 220px"
          @keyup.enter="resetAndSearch"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="resetAndSearch">查询</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="scanLimited"
      type="warning"
      :closable="false"
      title="本次扫描达到字节预算上限，较早的日志未参与检索；请缩小时间范围后重试。"
      class="scan-alert"
    />

    <el-table v-loading="loading && items.length === 0" :data="items" size="small" class="logs-table">
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ formatTimestamp(row.timestamp) }}</template>
      </el-table-column>
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag :type="levelTagType(row.level)" size="small">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="组件" prop="component" width="90" />
      <el-table-column label="模块" prop="module" width="200" show-overflow-tooltip />
      <el-table-column label="日志摘要" min-width="360">
        <template #default="{ row }">
          <span class="log-message">{{ row.message }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="没有匹配的日志" :image-size="64" />
      </template>
    </el-table>

    <div v-if="hasMore" class="load-more">
      <el-button :loading="loading" @click="loadMore">加载更多</el-button>
    </div>

    <el-drawer v-model="drawerVisible" title="日志详情" size="620px" destroy-on-close>
      <div v-if="detail" class="detail-body">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="时间">{{ formatTimestamp(detail.timestamp) }}</el-descriptions-item>
          <el-descriptions-item label="级别">
            <el-tag :type="levelTagType(detail.level)" size="small">{{ detail.level }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="组件">{{ detail.component }}</el-descriptions-item>
          <el-descriptions-item label="模块">{{ detail.module || "-" }}</el-descriptions-item>
          <el-descriptions-item label="Request ID">
            {{ detail.requestId ?? "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="Run ID">{{ detail.runId ?? "-" }}</el-descriptions-item>
          <el-descriptions-item label="来源文件" :span="2">
            {{ detail.source.filePath }}#{{ detail.source.lineNumber }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="section-title">完整消息</h4>
        <pre class="code-block">{{ detail.message }}</pre>

        <template v-if="detail.exception">
          <h4 class="section-title">异常堆栈</h4>
          <pre class="code-block exception">{{ detail.exception }}</pre>
        </template>

        <h4 class="section-title">原始 JSON</h4>
        <pre class="code-block">{{ rawJson }}</pre>

        <div class="detail-actions">
          <el-button size="small" @click="copyDetail">复制日志</el-button>
          <el-button v-if="detail.exception" size="small" @click="copyException">复制堆栈</el-button>
          <el-button v-if="detail.requestId" size="small" @click="filterByRequest">查看同一请求</el-button>
          <el-button size="small" :loading="contextLoading" @click="loadContext">
            {{ contextItems.length ? "刷新上下文" : "查看前后日志" }}
          </el-button>
        </div>

        <template v-if="contextItems.length">
          <h4 class="section-title">上下文（同文件前 20 条 / 后 20 条）</h4>
          <div class="context-list">
            <div
              v-for="item in contextItems"
              :key="item.eventId"
              class="context-row"
              :class="{ current: item.eventId === detail.eventId }"
            >
              <span class="context-time">{{ formatTimestamp(item.timestamp) }}</span>
              <el-tag :type="levelTagType(item.level)" size="small">{{ item.level }}</el-tag>
              <span class="context-message">{{ item.message }}</span>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getDiagnosticsLogContext,
  getDiagnosticsLogDetail,
  searchDiagnosticsLogs,
  type DiagnosticsLogDetail,
  type DiagnosticsLogEntry,
} from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import {
  COMPONENT_OPTIONS,
  LEVEL_OPTIONS,
  copyText,
  formatTimestamp,
  levelTagType,
} from "./utils";

const PAGE_SIZE = 100;

const filters = reactive({ component: "", level: "", keyword: "", requestId: "" });
const timeRange = ref<"all" | "1h" | "24h" | "7d">("24h");
const items = ref<DiagnosticsLogEntry[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const scanLimited = ref(false);
const loading = ref(false);

const drawerVisible = ref(false);
const detail = ref<DiagnosticsLogDetail | null>(null);
const contextLoading = ref(false);
const contextItems = ref<DiagnosticsLogEntry[]>([]);

const rawJson = computed(() =>
  detail.value ? JSON.stringify(detail.value.raw, null, 2) : "",
);

function timeFromIso(): string | undefined {
  if (timeRange.value === "all") return undefined;
  const spanMs =
    timeRange.value === "1h"
      ? 3600_000
      : timeRange.value === "24h"
        ? 24 * 3600_000
        : 7 * 24 * 3600_000;
  return new Date(Date.now() - spanMs).toISOString();
}

function activeFilters(): Record<string, string> {
  return {
    component: filters.component,
    level: filters.level,
    keyword: filters.keyword.trim(),
    requestId: filters.requestId.trim(),
    from: timeFromIso() ?? "",
  };
}

async function search(reset: boolean): Promise<void> {
  loading.value = true;
  try {
    const page = await searchDiagnosticsLogs({
      ...activeFilters(),
      limit: PAGE_SIZE,
      cursor: reset ? undefined : (cursor.value ?? undefined),
    });
    const pageItems = page.items ?? [];
    items.value = reset ? pageItems : [...items.value, ...pageItems];
    cursor.value = page.nextCursor ?? null;
    hasMore.value = page.hasMore;
    scanLimited.value = page.scanLimited;
  } catch (caught) {
    ElMessage.error(errorMessage(caught));
  } finally {
    loading.value = false;
  }
}

function resetAndSearch(): void {
  cursor.value = null;
  void search(true);
}

function loadMore(): void {
  void search(false);
}

async function openDetail(entry: DiagnosticsLogEntry): Promise<void> {
  drawerVisible.value = true;
  detail.value = null;
  contextItems.value = [];
  try {
    detail.value = await getDiagnosticsLogDetail(entry.eventId);
  } catch (caught) {
    drawerVisible.value = false;
    ElMessage.error(errorMessage(caught));
  }
}

async function loadContext(): Promise<void> {
  if (!detail.value) return;
  contextLoading.value = true;
  try {
    const body = await getDiagnosticsLogContext(detail.value.eventId, 20, 20);
    contextItems.value = body.items ?? [];
  } catch (caught) {
    ElMessage.error(errorMessage(caught));
  } finally {
    contextLoading.value = false;
  }
}

function filterByRequest(): void {
  if (!detail.value?.requestId) return;
  filters.requestId = detail.value.requestId;
  drawerVisible.value = false;
  resetAndSearch();
}

async function copyDetail(): Promise<void> {
  if (!detail.value) return;
  if (
    await copyText(
      JSON.stringify({ ...detail.value.raw, source: detail.value.source }, null, 2),
    )
  ) {
    ElMessage.success("已复制日志");
  }
}

async function copyException(): Promise<void> {
  if (!detail.value?.exception) return;
  if (await copyText(detail.value.exception)) ElMessage.success("已复制异常堆栈");
}
</script>

<style scoped>
.logs-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.filter-bar {
  margin-bottom: 0;
}

.scan-alert {
  margin-bottom: 8px;
}

.log-message {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.load-more {
  display: flex;
  justify-content: center;
  padding: 4px 0;
}

.detail-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  margin: 12px 0 4px;
  font-size: 13px;
  color: var(--text-strong, #111827);
}

.code-block {
  margin: 0;
  padding: 10px;
  background: rgba(15, 23, 42, 0.04);
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
}

.code-block.exception {
  color: #b91c1c;
}

.detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.context-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow: auto;
}

.context-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.context-row.current {
  background: var(--brand-50, rgba(10, 186, 181, 0.08));
}

.context-time {
  flex-shrink: 0;
  color: var(--text-faint, #6b7280);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.context-message {
  word-break: break-all;
}
</style>
