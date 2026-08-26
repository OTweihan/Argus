<template>
  <div class="runs-panel">
    <div class="panel-toolbar">
      <el-button size="large" type="primary" plain :loading="loading" @click="loadRuns">
        刷新会话
      </el-button>
      <span class="hint">启动会话按 outputs/logs/dev 目录识别，保留 14 天</span>
    </div>

    <el-table v-loading="loading" :data="runs" size="default">
      <el-table-column label="Run ID" prop="runId" min-width="200">
        <template #default="{ row }">
          <span class="run-id">{{ row.runId }}</span>
        </template>
      </el-table-column>
      <el-table-column label="开始时间" width="180">
        <template #default="{ row }">{{ formatTimestamp(row.startedAt) }}</template>
      </el-table-column>
      <el-table-column label="日志文件数" width="110">
        <template #default="{ row }">{{ row.files.length }}</template>
      </el-table-column>
      <el-table-column label="占用空间" width="120">
        <template #default="{ row }">{{ formatBytes(row.totalBytes) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openRunLogs(row)">查看日志</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无启动会话（使用 node scripts/dev.mjs 启动后生成）" :image-size="64" />
      </template>
    </el-table>

    <el-drawer v-model="drawerVisible" :title="`会话日志 · ${activeRun?.runId ?? ''}`" size="720px" destroy-on-close>
      <div class="run-logs-body">
        <el-form inline @submit.prevent>
          <el-form-item label="组件">
            <el-select v-model="runFilters.component" style="width: 130px" @change="resetRunSearch">
              <el-option
                v-for="opt in COMPONENT_OPTIONS"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="级别">
            <el-select v-model="runFilters.level" style="width: 120px" @change="resetRunSearch">
              <el-option
                v-for="opt in LEVEL_OPTIONS"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="关键词">
            <el-input
              v-model="runFilters.keyword"
              clearable
              style="width: 180px"
              @keyup.enter="resetRunSearch"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="logsLoading" @click="resetRunSearch">查询</el-button>
          </el-form-item>
        </el-form>

        <div v-loading="logsLoading && runItems.length === 0" class="run-logs-list">
          <div
            v-for="item in runItems"
            :key="item.eventId"
            class="run-log-row"
          >
            <span class="run-log-time">{{ formatTimestamp(item.timestamp) }}</span>
            <el-tag :type="levelTagType(item.level)" size="small">{{ item.component }}</el-tag>
            <span class="run-log-message">{{ item.message }}</span>
          </div>
          <el-empty v-if="!logsLoading && runItems.length === 0" description="没有匹配的会话日志" :image-size="64" />
        </div>

        <div v-if="runHasMore" class="load-more">
          <el-button size="small" :loading="logsLoading" @click="loadMoreRunLogs">加载更多</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  listDiagnosticsRuns,
  searchDiagnosticsRunLogs,
  type DiagnosticsLogEntry,
  type RunSummary,
} from "../../api/diagnostics";
import { errorMessage } from "../../utils";
import {
  COMPONENT_OPTIONS,
  LEVEL_OPTIONS,
  formatBytes,
  formatTimestamp,
  levelTagType,
} from "./utils";

const PAGE_SIZE = 100;

const loading = ref(false);
const runs = ref<RunSummary[]>([]);

const drawerVisible = ref(false);
const activeRun = ref<RunSummary | null>(null);
const runFilters = reactive({ component: "", level: "", keyword: "" });
const runItems = ref<DiagnosticsLogEntry[]>([]);
const runCursor = ref<string | null>(null);
const runHasMore = ref(false);
const logsLoading = ref(false);

async function loadRuns(): Promise<void> {
  loading.value = true;
  try {
    const body = await listDiagnosticsRuns(50);
    runs.value = body.runs ?? [];
  } catch (caught) {
    ElMessage.error(errorMessage(caught));
  } finally {
    loading.value = false;
  }
}

function openRunLogs(run: RunSummary): void {
  activeRun.value = run;
  runFilters.component = "";
  runFilters.level = "";
  runFilters.keyword = "";
  drawerVisible.value = true;
  resetRunSearch();
}

async function searchRunLogs(reset: boolean): Promise<void> {
  if (!activeRun.value) return;
  logsLoading.value = true;
  try {
    const page = await searchDiagnosticsRunLogs(
      activeRun.value.runId,
      {
        component: runFilters.component,
        level: runFilters.level,
        keyword: runFilters.keyword.trim(),
        limit: PAGE_SIZE,
        cursor: reset ? undefined : (runCursor.value ?? undefined),
      },
    );
    const pageItems = page.items ?? [];
    runItems.value = reset ? pageItems : [...runItems.value, ...pageItems];
    runCursor.value = page.nextCursor ?? null;
    runHasMore.value = page.hasMore;
  } catch (caught) {
    ElMessage.error(errorMessage(caught));
  } finally {
    logsLoading.value = false;
  }
}

function resetRunSearch(): void {
  runCursor.value = null;
  void searchRunLogs(true);
}

function loadMoreRunLogs(): void {
  void searchRunLogs(false);
}
</script>

<style scoped>
.runs-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hint {
  color: var(--text-faint, #6b7280);
  font-size: 12px;
}

.run-id {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.run-logs-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.run-logs-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 200px;
}

.run-log-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.03);
  font-size: 12px;
}

.run-log-time {
  flex-shrink: 0;
  color: var(--text-faint, #6b7280);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.run-log-message {
  word-break: break-all;
  white-space: pre-wrap;
}

.load-more {
  display: flex;
  justify-content: center;
}
</style>
