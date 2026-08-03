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
      <el-table-column label="候选数" width="70">
        <template #default="{ row }">
          {{ row.candidateCount }}
        </template>
      </el-table-column>
    </el-table>
    <div v-if="hasMore" class="list-more">
      <el-button size="small" :loading="loading" @click="$emit('load-more')">
        加载更多
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { EndpointEvidenceInfo } from "../../../../api/correlation";
import { httpMethodTag } from "../../../../utils";

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

.list-more {
  margin-top: 8px;
  text-align: center;
}

.conf-high { color: #059669; font-weight: 600; }
.conf-medium { color: #d97706; font-weight: 600; }
.conf-low { color: #6b7280; }
.conf-unknown { color: #9ca3af; }

.candidate-hint {
  font-size: 12px;
  color: var(--text-faint);
}

.text-faint {
  color: var(--text-faint);
}
</style>
