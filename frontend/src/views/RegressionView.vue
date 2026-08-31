<template>
  <div class="regression-view">
    <section class="page-intro">
      <div>
        <p class="eyebrow">QUALITY WORKSPACE</p>
        <h2>回归测试</h2>
        <p class="intro-copy">沉淀稳定用例，持续比较每次运行与质量基线。</p>
      </div>
      <div class="intro-mark" aria-hidden="true">R</div>
    </section>

    <el-alert
      v-if="!projects.length"
      type="info"
      :closable="false"
      show-icon
      title="还没有项目"
      description="请先在「项目」页创建测试项目，再回到这里配置回归用例。"
      class="empty-project-alert"
    />

    <template v-else>
      <section class="control-card">
        <div class="project-picker">
          <span class="field-label">当前项目</span>
          <el-select
            :model-value="store.selectedProjectId.value"
            placeholder="选择项目"
            filterable
            size="large"
            @update:model-value="store.selectProject($event)"
          >
            <el-option
              v-for="project in projects"
              :key="project.projectId"
              :value="project.projectId"
              :label="project.name"
            />
          </el-select>
          <el-tag v-if="store.baselineRunId.value" type="warning" effect="plain">
            基线 · {{ compactId(store.baselineRunId.value) }}
          </el-tag>
          <el-tag v-else type="info" effect="plain">尚未设置基线</el-tag>
        </div>

        <div class="quick-stats">
          <div class="stat-item">
            <span>用例</span>
            <strong>{{ store.cases.value.length }}</strong>
          </div>
          <div class="stat-item">
            <span>已启用</span>
            <strong>{{ enabledCaseCount }}</strong>
          </div>
          <div class="stat-item">
            <span>历史批次</span>
            <strong>{{ store.runsTotal.value }}</strong>
          </div>
        </div>

        <el-tooltip
          :disabled="store.selectedProjectHasCases.value"
          content="至少启用一个回归用例后才能发起批次"
          placement="bottom"
        >
          <span>
            <el-button
              type="primary"
              size="large"
              :disabled="!store.selectedProjectHasCases.value || store.startingRun.value"
              :loading="store.startingRun.value"
              @click="store.startRun()"
            >
              发起回归批次
            </el-button>
          </span>
        </el-tooltip>
      </section>

      <el-tabs v-model="activeTab" class="content-card">
        <el-tab-pane label="回归用例" name="cases">
          <el-table v-loading="store.casesLoading.value" :data="store.cases.value" size="default">
            <el-table-column prop="displayOrder" label="#" width="56" />
            <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
            <el-table-column label="类型" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.taskType === 'whitebox' ? 'warning' : 'primary'">
                  {{ row.taskType === "whitebox" ? "白盒" : "黑盒" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="goal" label="目标" min-width="220" show-overflow-tooltip />
            <el-table-column prop="maxSteps" label="步数" width="70" />
            <el-table-column prop="timeoutSeconds" label="超时(s)" width="86" />
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="store.toggleEnabled(row)" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="store.openEditCaseDialog(row)">
                  编辑
                </el-button>
                <el-button link type="danger" size="small" @click="onRemoveCase(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="cases-footer">
            <el-button type="primary" plain @click="store.openNewCaseDialog()">新建用例</el-button>
            <span class="hint">用例保存时会按任务创建规则校验（URL、模型配置、白盒配置等）。</span>
          </div>
        </el-tab-pane>

        <el-tab-pane
          :label="`批次历史${store.runsTotal.value ? `（${store.runsTotal.value}）` : ''}`"
          name="runs"
        >
          <el-table v-loading="store.runsLoading.value" :data="store.runs.value" size="default">
            <el-table-column prop="runId" label="批次 ID" min-width="200" show-overflow-tooltip />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="runTagType(row.status)">
                  {{ runLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="门禁" width="96">
              <template #default="{ row }">
                <el-tag
                  v-if="row.gateResult"
                  size="small"
                  :type="row.gateResult === 'passed' ? 'success' : 'danger'"
                >
                  {{ row.gateResult === "passed" ? "通过" : "未通过" }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="基线" width="70">
              <template #default="{ row }">
                <el-tag v-if="row.isBaseline" size="small" type="warning">是</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="store.openRunDetail(row.runId)">
                  详情
                </el-button>
                <el-button
                  v-if="row.status === 'completed' && !row.isBaseline"
                  link
                  type="warning"
                  size="small"
                  @click="store.markBaseline(row)"
                >
                  设为基线
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <RegressionCaseDialog
        :store="store"
        @close="store.showCaseDialog.value = false"
        @save="store.saveCase()"
      />
      <RegressionRunDrawer :store="store" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";

import RegressionCaseDialog from "../components/regression/RegressionCaseDialog.vue";
import RegressionRunDrawer from "../components/regression/RegressionRunDrawer.vue";
import type { RegressionCaseInfo } from "../api/regression";
import { injectConsoleApp } from "../composables/useConsoleApp";
import { useRegression } from "../composables/useRegression";

const consoleApp = injectConsoleApp();

const store = useRegression({ error: consoleApp.error, message: consoleApp.message });
// 模板直接访问的项目列表（来自全局控制台状态）
const projects = consoleApp.projects;
// 默认选中第一个项目；项目列表异步到达后同样生效
watch(
  projects,
  (list) => {
    const selectionStillExists = list.some(
      (project) => project.projectId === store.selectedProjectId.value,
    );
    if (!selectionStillExists && list[0]) {
      store.selectProject(list[0].projectId);
    }
  },
  { immediate: true },
);

const activeTab = ref("cases");
const enabledCaseCount = computed(() => store.cases.value.filter((item) => item.enabled).length);

async function onRemoveCase(row: RegressionCaseInfo): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除用例「${row.name}」？历史批次不受影响。`, "删除确认", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    return;
  }
  await store.removeCase(row);
}

function compactId(id: string): string {
  return id.length > 24 ? `${id.slice(0, 21)}...` : id;
}

function formatTime(value?: string | null): string {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

function runTagType(status: string): "info" | "warning" | "success" | "danger" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "warning";
  return "info";
}

function runLabel(status: string): string {
  const map: Record<string, string> = {
    pending: "准备中",
    running: "执行中",
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消",
  };
  return map[status] ?? status;
}
</script>

<style scoped>
.regression-view {
  flex: 1;
  min-height: 0;
  padding: 4px 0 8px;
  overflow: auto;
}

.page-intro {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 104px;
  margin-bottom: 14px;
  padding: 22px 26px;
  border: 1px solid rgba(10, 186, 181, 0.18);
  border-radius: var(--radius-md);
  background:
    radial-gradient(circle at 88% 30%, rgba(10, 186, 181, 0.16), transparent 34%),
    var(--surface-glass-strong);
  box-shadow: var(--shadow-panel);
  backdrop-filter: blur(var(--blur-soft));
}

.eyebrow {
  margin: 0 0 5px;
  color: var(--brand-600);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.page-intro h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: 23px;
  letter-spacing: -0.02em;
  line-height: 1.25;
}

.intro-copy {
  margin: 7px 0 0;
  color: var(--text-faint);
  font-size: 13px;
}

.intro-mark {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border: 1px solid rgba(10, 186, 181, 0.22);
  border-radius: 18px;
  color: var(--brand-600);
  background: var(--brand-gradient-soft);
  font-size: 25px;
  font-weight: 800;
  box-shadow: var(--shadow-xs);
}

.empty-project-alert {
  border-radius: var(--radius-md);
}

.control-card {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 14px;
  padding: 16px 18px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-panel);
  backdrop-filter: blur(var(--blur-soft));
}

.project-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.project-picker :deep(.el-select) {
  width: 240px;
}

.field-label {
  color: var(--text-faint, #6b7280);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.quick-stats {
  flex: 1;
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.stat-item {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 84px;
  padding: 8px 11px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(248, 250, 252, 0.66));
  box-shadow: var(--shadow-xs);
}

.stat-item span {
  color: var(--text-faint);
  font-size: 12px;
}

.stat-item strong {
  color: var(--text-strong);
  font-size: 17px;
}

.content-card {
  padding: 0 20px 18px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-glass-strong);
  box-shadow: var(--shadow-panel);
  backdrop-filter: blur(var(--blur-soft));
}

.content-card :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.content-card :deep(.el-tabs__item) {
  height: 52px;
  font-weight: 650;
}

.cases-footer {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.hint {
  font-size: 12px;
  color: var(--text-faint, #6b7280);
}

@media (max-width: 1050px) {
  .control-card {
    align-items: stretch;
    flex-wrap: wrap;
  }

  .quick-stats {
    order: 3;
    flex-basis: 100%;
    justify-content: flex-start;
  }
}

@media (max-width: 720px) {
  .page-intro {
    padding: 18px;
  }

  .intro-mark {
    display: none;
  }

  .project-picker {
    align-items: stretch;
    flex: 1 1 100%;
    flex-wrap: wrap;
  }

  .project-picker :deep(.el-select) {
    width: 100%;
  }

  .quick-stats {
    overflow-x: auto;
  }
}
</style>
