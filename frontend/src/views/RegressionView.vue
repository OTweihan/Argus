<template>
  <div class="regression-view">
    <el-alert
      v-if="!projects.length"
      type="info"
      :closable="false"
      title="还没有项目"
      description="请先在「项目」页创建测试项目，再回到这里配置回归用例。"
    />

    <template v-else>
      <section class="toolbar">
        <span class="label">项目</span>
        <el-select
          :model-value="store.selectedProjectId.value"
          placeholder="选择项目"
          filterable
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
          基线：{{ compactId(store.baselineRunId.value) }}
        </el-tag>
        <el-tag v-else type="info" effect="plain">尚未设置基线</el-tag>

        <div class="spacer" />
        <el-button
          type="primary"
          :disabled="!store.selectedProjectHasCases.value || store.startingRun.value"
          :loading="store.startingRun.value"
          @click="store.startRun()"
        >
          发起回归批次
        </el-button>
      </section>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="回归用例" name="cases">
          <el-table
            v-loading="store.casesLoading.value"
            :data="store.cases.value"
            size="default"
          >
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
                <el-switch
                  :model-value="row.enabled"
                  @change="store.toggleEnabled(row)"
                />
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
            <el-button size="small" @click="store.openNewCaseDialog()">新建用例</el-button>
            <span class="hint">用例保存时会按任务创建规则校验（URL、模型配置、白盒配置等）。</span>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`批次历史${store.runsTotal.value ? `（${store.runsTotal.value}）` : ''}`" name="runs">
          <el-table v-loading="store.runsLoading.value" :data="store.runs.value" size="default">
            <el-table-column prop="runId" label="批次 ID" min-width="200" show-overflow-tooltip />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="runTagType(row.status)">{{ runLabel(row.status) }}</el-tag>
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
import { ref, watch } from "vue";
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
    if (!store.selectedProjectId.value && list[0]) {
      store.selectProject(list[0].projectId);
    }
  },
  { immediate: true },
);

const activeTab = ref("cases");

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
  padding: 4px 8px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.toolbar .label {
  color: var(--text-faint, #6b7280);
  font-size: 13px;
}
.spacer {
  flex: 1;
}
.cases-footer {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.hint {
  font-size: 12px;
  color: var(--text-faint, #6b7280);
}
</style>
