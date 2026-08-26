<template>
  <el-drawer
    :model-value="store.showDetail.value"
    size="62%"
    :destroy-on-close="false"
    @update:model-value="onVisibilityChange"
  >
    <template #header>
      <div class="drawer-header">
        <h3>批次详情</h3>
        <el-tag v-if="run" :type="statusTagType(run.status)">{{ statusLabel(run.status) }}</el-tag>
        <el-tag v-if="run?.gateResult" :type="gateTagType(run.gateResult)">
          {{ run.gateResult === "passed" ? "门禁通过" : "门禁失败" }}
        </el-tag>
        <el-tag v-if="run?.isBaseline" type="warning">当前基线</el-tag>
      </div>
    </template>

    <div v-loading="store.detailLoading.value" class="drawer-body">
      <template v-if="detail">
        <section class="meta">
          <p><span class="label">批次 ID</span>{{ detail.run.runId }}</p>
          <p v-if="detail.run.baselineRunId">
            <span class="label">对比基线</span>{{ detail.run.baselineRunId }}
          </p>
          <p v-if="detail.run.startedAt">
            <span class="label">开始时间</span>{{ formatTime(detail.run.startedAt) }}
          </p>
          <p v-if="detail.run.completedAt">
            <span class="label">结束时间</span>{{ formatTime(detail.run.completedAt) }}
          </p>
          <p v-if="detail.run.errorMessage" class="error-line">
            <span class="label">错误</span>{{ detail.run.errorMessage }}
          </p>
          <div class="actions">
            <el-button
              v-if="!isTerminal"
              type="danger"
              plain
              size="small"
              @click="store.cancelCurrentRun()"
            >
              取消批次
            </el-button>
            <el-button
              v-if="detail.run.status === 'completed' && !detail.run.isBaseline"
              type="primary"
              plain
              size="small"
              @click="store.markBaseline(detail.run)"
            >
              设为基线
            </el-button>
            <el-button size="small" @click="store.refreshDetail()">刷新</el-button>
          </div>
        </section>

        <!-- 汇总与差异 -->
        <section v-if="summary && summary.gateResult" class="summary-block">
          <h4>质量门禁</h4>
          <el-alert
            :type="summary.gateResult === 'passed' ? 'success' : 'error'"
            :closable="false"
            :title="
              summary.gateResult === 'passed'
                ? '本次批次通过质量门禁'
                : '本次批次未通过质量门禁'
            "
          >
            <div v-for="(reason, idx) in summary.blockingReasons ?? []" :key="idx" class="reason">
              · {{ reason }}
            </div>
          </el-alert>

          <div v-if="diffSummary" class="diff-counts">
            <el-tag type="danger">新增 {{ diffSummary.addedCount ?? 0 }}</el-tag>
            <el-tag type="info">持续 {{ diffSummary.persistentCount ?? 0 }}</el-tag>
            <el-tag type="success">已解决 {{ diffSummary.resolvedCount ?? 0 }}</el-tag>
            <span class="totals">
              问题：当前 {{ findingTotals.current ?? 0 }} / 基线
              {{ findingTotals.baseline ?? 0 }}
            </span>
          </div>

          <template v-for="group in diffGroups" :key="group.key">
            <details v-if="group.entries.length" class="diff-group">
              <summary>{{ group.title }}（{{ group.entries.length }}）</summary>
              <el-table :data="group.entries" size="small" max-height="260">
                <el-table-column prop="severity" label="级别" width="90" />
                <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
                <el-table-column prop="location" label="位置" min-width="160" show-overflow-tooltip />
                <el-table-column prop="caseId" label="用例" width="180" show-overflow-tooltip />
              </el-table>
            </details>
          </template>
        </section>

        <!-- 批次项 -->
        <section class="items-block">
          <h4>批次项（{{ items.length }}）</h4>
          <el-table :data="items" size="small">
            <el-table-column prop="displayOrder" label="#" width="50" />
            <el-table-column prop="caseName" label="用例" min-width="140" show-overflow-tooltip />
            <el-table-column label="批次状态" width="110">
              <template #default="{ row }">
                <el-tag :type="itemTagType(row.status)" size="small">
                  {{ itemLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="任务状态" width="100">
              <template #default="{ row }">{{ row.taskStatus ?? "-" }}</template>
            </el-table-column>
            <el-table-column prop="findingCount" label="问题数" width="80" />
            <el-table-column label="报告" width="80">
              <template #default="{ row }">
                <a
                  v-if="row.taskStatus === 'completed'"
                  :href="`/#/task-detail/${row.taskId}`"
                  @click.prevent="gotoTask(row.taskId)"
                >
                  查看
                </a>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </template>
      <el-empty v-else-if="!store.detailLoading.value" description="批次不存在或已被删除" />
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { RegressionDiffEntryInfo } from "../../api/regression";
import { injectConsoleApp } from "../../composables/useConsoleApp";
import type { RegressionStore } from "../../composables/useRegression";

const props = defineProps<{ store: RegressionStore }>();
const consoleApp = injectConsoleApp();

const detail = computed(() => props.store.detail.value);
const run = computed(() => detail.value?.run ?? null);
const items = computed(() => detail.value?.items ?? []);
const summary = computed(() => detail.value?.summary ?? null);
const isTerminal = computed(() =>
  run.value ? ["completed", "failed", "cancelled"].includes(run.value.status) : false,
);

const diffSummary = computed(() => summary.value?.diff ?? null);
const findingTotals = computed(
  () => (summary.value?.findingTotals ?? {}) as Record<string, number | undefined>,
);

interface DiffGroup {
  key: string;
  title: string;
  entries: RegressionDiffEntryInfo[];
}

const diffGroups = computed<DiffGroup[]>(() => {
  const diff = summary.value?.diff ?? {};
  return [
    { key: "added", title: "新增问题", entries: (diff.added ?? []) as RegressionDiffEntryInfo[] },
    {
      key: "persistent",
      title: "持续问题",
      entries: (diff.persistent ?? []) as RegressionDiffEntryInfo[],
    },
    {
      key: "resolved",
      title: "已解决问题",
      entries: (diff.resolved ?? []) as RegressionDiffEntryInfo[],
    },
  ];
});

function onVisibilityChange(visible: boolean): void {
  if (!visible) props.store.closeDetail();
}

function gotoTask(taskId: string): void {
  props.store.closeDetail();
  consoleApp.changeView("task-detail");
  window.location.hash = `task-detail/${taskId}`;
  consoleApp.selectTask(taskId);
}

function formatTime(value: string): string {
  return value.replace("T", " ").slice(0, 19);
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: "准备中",
    running: "执行中",
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消",
  };
  return map[status] ?? status;
}

function statusTagType(status: string): "info" | "warning" | "success" | "danger" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "warning";
  return "info";
}

function gateTagType(gate: string): "success" | "danger" {
  return gate === "passed" ? "success" : "danger";
}

function itemTagType(status: string): "info" | "warning" | "success" | "danger" | "primary" {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
    case "timeout":
      return "danger";
    case "cancelled":
    case "skipped":
      return "info";
    case "running":
      return "warning";
    default:
      return "primary";
  }
}

function itemLabel(status: string): string {
  const map: Record<string, string> = {
    pending: "等待",
    running: "执行中",
    completed: "成功",
    failed: "失败",
    timeout: "超时",
    cancelled: "取消",
    skipped: "跳过",
  };
  return map[status] ?? status;
}
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.drawer-header h3 {
  margin: 0;
  margin-right: 8px;
}
.drawer-body {
  padding: 0 4px;
}
.meta p {
  margin: 6px 0;
  font-size: 13px;
}
.meta .label {
  display: inline-block;
  width: 76px;
  color: var(--text-faint, #6b7280);
}
.error-line {
  color: var(--el-color-danger);
}
.actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.summary-block,
.items-block {
  margin-top: 20px;
}
.summary-block h4,
.items-block h4 {
  margin: 0 0 10px;
}
.diff-counts {
  margin: 12px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.totals {
  font-size: 12px;
  color: var(--text-faint, #6b7280);
}
.diff-group {
  margin: 8px 0;
}
.diff-group summary {
  cursor: pointer;
  font-size: 13px;
}
.reason {
  font-size: 12px;
}
</style>
