<template>
  <div class="list-wrap">
    <div class="list-toolbar">
      <span v-if="total !== null" class="list-count">
        共 {{ total }} 条 (已确认 {{ confirmedCount }} / 候选 {{ candidateCount }})
      </span>
    </div>
    <el-table :data="items" size="small" stripe style="width: 100%">
      <el-table-column label="缺陷" min-width="220">
        <template #default="{ row }">
          <template v-if="row.findingInfo">
            <div class="finding-title-row">
              <span class="finding-title">{{ row.findingInfo.title }}</span>
              <span
                :class="['severity-tag', `tag-${(row.findingInfo.severity ?? '').toLowerCase()}`]"
              >
                {{ row.findingInfo.severity }}
              </span>
            </div>
            <div class="finding-meta-row">
              <code v-if="row.findingInfo.ruleId" class="mono">{{ row.findingInfo.ruleId }}</code>
              <span v-if="row.findingInfo.location" class="mono loc">{{
                row.findingInfo.location
              }}</span>
            </div>
          </template>
          <span v-else class="text-hint">-</span>
        </template>
      </el-table-column>
      <el-table-column label="关联类型" width="130">
        <template #default="{ row }">
          <el-tag size="small" :type="relationTag(row.bestRelationType)">
            {{ relationLabel(row.bestRelationType) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="调用距离" width="90">
        <template #default="{ row }">
          <span v-if="row.minimumCallDistance === null || row.minimumCallDistance === -1">-</span>
          <span v-else-if="row.minimumCallDistance === 0" class="dist-direct">处理方法内</span>
          <span v-else>{{ row.minimumCallDistance }}</span>
        </template>
      </el-table-column>
      <el-table-column label="确认请求数" width="100">
        <template #default="{ row }">
          <span class="count-confirmed">{{ row.confirmedRequestCount }}</span>
        </template>
      </el-table-column>
      <el-table-column label="候选请求数" width="100">
        <template #default="{ row }">
          {{ row.candidateRequestCount }}
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="200">
        <template #default>
          <span class="text-hint">静态可达，不代表该分支实际执行</span>
        </template>
      </el-table-column>
      <template #append>
        <InfiniteScrollLoad
          :has-more="hasMore"
          :loading="loading"
          @load-more="$emit('load-more')"
        />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { FindingEvidenceInfo } from "../../../../api/correlation";
import InfiniteScrollLoad from "../../../common/InfiniteScrollLoad.vue";

const props = defineProps<{
  items: FindingEvidenceInfo[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
}>();

defineEmits<{ "load-more": [] }>();

const confirmedCount = computed(
  () => props.items.filter((f) => f.confirmedRequestCount > 0).length,
);

const candidateCount = computed(
  () => props.items.filter((f) => f.candidateRequestCount > 0).length,
);

type ElTagType = "success" | "info" | "danger" | "warning" | "primary";

function relationTag(r: string): ElTagType {
  switch (r) {
    case "DIRECT_HANDLER":
      return "success";
    case "STATIC_REACHABLE":
      return "primary";
    case "FLOW_MEMBER":
      return "warning";
    default:
      return "info";
  }
}

function relationLabel(r: string): string {
  switch (r) {
    case "DIRECT_HANDLER":
      return "直接处理函数";
    case "STATIC_REACHABLE":
      return "静态可达";
    case "FLOW_MEMBER":
      return "执行流成员";
    default:
      return r;
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

.count-confirmed {
  color: #059669;
  font-weight: 600;
}

.finding-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.finding-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.severity-tag {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}

.tag-critical {
  background: #fee2e2;
  color: #b91c1c;
}
.tag-high {
  background: #ffedd5;
  color: #c2410c;
}
.tag-medium {
  background: #fef9c3;
  color: #a16207;
}
.tag-low {
  background: #dcfce7;
  color: #15803d;
}
.tag-info {
  background: #e0f2fe;
  color: #0369a1;
}

.finding-meta-row {
  display: flex;
  gap: 12px;
  margin-top: 2px;
  font-size: 12px;
}

.finding-meta-row .mono {
  color: #64748b;
}

.loc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.dist-direct {
  color: #059669;
  font-size: 12px;
}

.text-hint {
  font-size: 12px;
  color: var(--text-faint);
  font-style: italic;
}
</style>
