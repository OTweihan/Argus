<template>
  <div class="list-wrap">
    <div class="list-toolbar">
      <el-select
        :model-value="statusFilter"
        size="small"
        placeholder="匹配状态"
        clearable
        style="width:160px"
        @change="onFilterChange"
      >
        <el-option label="全部" value="" />
        <el-option label="唯一匹配" value="UNIQUE" />
        <el-option label="歧义" value="AMBIGUOUS" />
        <el-option label="未匹配" value="UNMATCHED" />
      </el-select>
      <span v-if="total !== null" class="list-count">共 {{ total }} 条</span>
    </div>
    <el-table :data="items" size="small" stripe style="width:100%" max-height="400">
      <el-table-column label="请求" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="httpMethodTag(row.httpMethod ?? row.requestPath ?? '')">
            {{ row.httpMethod ?? '-' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="请求路径" min-width="180">
        <template #default="{ row }">
          <span class="mano">{{ row.displayPath || row.requestPath || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="匹配方式" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="strategyTag(row.matchStrategy)">
            {{ strategyLabel(row.matchStrategy) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="resolutionTag(row.resolutionStatus)">
            {{ resolutionLabel(row.resolutionStatus) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="置信度" width="80">
        <template #default="{ row }">
          <span :class="`conf-${row.confidence?.toLowerCase()}`">{{ row.confidence }}</span>
        </template>
      </el-table-column>
      <el-table-column label="匹配端点" min-width="200">
        <template #default="{ row }">
          <template v-if="row.matchedEndpointInfo">
            <span class="mano">{{ row.matchedEndpointInfo.httpMethod }}</span>
            <span class="mano" style="margin-left:6px">{{ row.matchedEndpointInfo.normalizedPath }}</span>
          </template>
          <span v-else-if="row.candidates?.length > 0" class="candidate-hint">
            候选 {{ row.candidates.length }} 个
          </span>
          <span v-else class="text-faint">-</span>
        </template>
      </el-table-column>
      <el-table-column label="调用流" min-width="220">
        <template #default="{ row }">
          <template v-if="row.executionFlows?.length">
            <el-collapse>
              <el-collapse-item
                v-for="flow in row.executionFlows"
                :key="flow.executionFlowId"
                :title="flow.entryPoint"
              >
                <template #title>
                  <span class="mono flow-entry">{{ flow.entryPoint }}</span>
                  <span class="badge depth">深度 {{ flow.callDepth }}</span>
                </template>
                <el-table :data="flow.steps ?? []" size="small" :show-header="false" style="width:100%">
                  <el-table-column label="深度" width="50">
                    <template #default="{ row: step }">
                      {{ step.depth }}
                    </template>
                  </el-table-column>
                  <el-table-column label="方法" min-width="200">
                    <template #default="{ row: step }">
                      <span class="mano">{{ step.className || "-" }}.{{ step.methodName || step.methodKey }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </template>
          <span v-else class="text-faint">-</span>
        </template>
      </el-table-column>
      <el-table-column label="候选数" width="70">
        <template #default="{ row }">
          {{ row.candidateCount }}
        </template>
      </el-table-column>
      <template #append>
        <InfiniteScrollLoad :has-more="hasMore" :loading="loading" @load-more="$emit('load-more')" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import type { EndpointEvidenceInfo } from "../../../../api/correlation";
import { httpMethodTag } from "../../../../utils";
import InfiniteScrollLoad from "../../../common/InfiniteScrollLoad.vue";

defineProps<{
  items: EndpointEvidenceInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
  statusFilter: string;
}>();

const emit = defineEmits<{
  "load-more": [];
  "filter-change": [status: string];
}>();

function onFilterChange(val: string | number | boolean | object | undefined): void {
  emit("filter-change", String(val ?? ""));
}

type ElTagType = "success" | "info" | "danger" | "warning" | "primary";

function strategyTag(s: string): ElTagType {
  switch (s) {
    case "EXACT": return "success";
    case "TEMPLATE": return "primary";
    case "PATH_ONLY": return "warning";
    default: return "info";
  }
}

function strategyLabel(s: string): string {
  switch (s) {
    case "EXACT": return "精确";
    case "TEMPLATE": return "模板";
    case "PATH_ONLY": return "仅路径";
    default: return s;
  }
}

function resolutionTag(r: string): ElTagType {
  switch (r) {
    case "UNIQUE": return "success";
    case "AMBIGUOUS": return "warning";
    case "UNMATCHED": return "danger";
    default: return "info";
  }
}

function resolutionLabel(r: string): string {
  switch (r) {
    case "UNIQUE": return "唯一";
    case "AMBIGUOUS": return "歧义";
    case "UNMATCHED": return "未匹配";
    default: return r;
  }
}
</script>

<style scoped>
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

.conf-high { color: #059669; font-weight: 600; }
.conf-medium { color: #d97706; font-weight: 600; }
.conf-low { color: #6b7280; }
.conf-unknown { color: #9ca3af; }

.candidate-hint {
  font-size: 12px;
  color: var(--text-faint);
}

.flow-entry {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge.depth {
  margin-left: 8px;
  font-size: 11px;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 0 6px;
  white-space: nowrap;
}

.text-faint {
  color: var(--text-faint);
}
</style>
