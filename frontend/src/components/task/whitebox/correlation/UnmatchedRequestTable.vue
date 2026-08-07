<template>
  <div class="list-wrap">
    <div class="list-toolbar">
      <span v-if="total !== null" class="list-count">共 {{ total }} 条未匹配请求</span>
    </div>
    <el-table :data="items" size="small" stripe style="width:100%">
      <el-table-column label="方法" width="70">
        <template #default="{ row }">
          <el-tag size="small" :type="httpMethodTag(row.httpMethod)">
            {{ row.httpMethod }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="路径" min-width="200">
        <template #default="{ row }">
          <span class="mano">{{ row.displayPath }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态码" width="80">
        <template #default="{ row }">
          <span :class="statusClass(row.responseStatus)">{{ row.responseStatus ?? '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="结果" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="outcomeTag(row.outcome)">
            {{ outcomeLabel(row.outcome) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="资格" width="100">
        <template #default="{ row }">
          <span class="faint-text">{{ eligibilityLabel(row.endpointMatchEligibility) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="步骤" width="140">
        <template #default="{ row }">
          <span v-if="row.stepExecutionId" class="faint-text">{{ row.stepExecutionId }}</span>
          <span v-else class="faint-text">-</span>
        </template>
      </el-table-column>
      <template #append>
        <InfiniteScrollLoad :has-more="hasMore" :loading="loading" @load-more="$emit('load-more')" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import type { HttpRequestEvidenceInfo } from "../../../../api/correlation";
import { httpMethodTag } from "../../../../utils";
import InfiniteScrollLoad from "../../../common/InfiniteScrollLoad.vue";

defineProps<{
  items: HttpRequestEvidenceInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{ "load-more": [] }>();

type ElTagType = "success" | "info" | "danger" | "warning" | "primary";

function statusClass(code: number | null): string {
  if (code === null) return "status-na";
  if (code >= 200 && code < 300) return "status-ok";
  if (code >= 400 && code < 500) return "status-err";
  if (code >= 500) return "status-fail";
  return "";
}

function outcomeTag(o: string): ElTagType {
  switch (o) {
    case "COMPLETED": return "success";
    case "NETWORK_FAILED": return "danger";
    case "ABANDONED": return "warning";
    default: return "info";
  }
}

function outcomeLabel(o: string): string {
  switch (o) {
    case "COMPLETED": return "已完成";
    case "NETWORK_FAILED": return "网络失败";
    case "ABANDONED": return "未完成";
    default: return o;
  }
}

function eligibilityLabel(e: string): string {
  switch (e) {
    case "CONFIRMED_ELIGIBLE": return "可匹配";
    case "ATTEMPT_ONLY": return "仅尝试";
    case "EXCLUDED_SW_CACHE": return "SW缓存";
    default: return e;
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

.status-ok  { color: #059669; font-weight: 600; }
.status-err { color: #d97706; font-weight: 600; }
.status-fail { color: #dc2626; font-weight: 600; }
.status-na  { color: #9ca3af; }

.faint-text {
  font-size: 12px;
  color: var(--text-faint);
}
</style>
