/**
 * 严重级别统一口径：顺序与排名。多个白盒组件（FindingList 排序、OverviewTab 计数）
 * 之前各自手写一份 CRITICAL/HIGH/MEDIUM/LOW/INFO 顺序，此处收敛为单一事实来源。
 */
export const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const;

export type Severity = (typeof SEVERITY_ORDER)[number];

/** severity 名 → 排序权重（越小越严重）。 */
export const SEVERITY_RANK: Readonly<Record<string, number>> = Object.freeze(
  Object.fromEntries(SEVERITY_ORDER.map((severity, index) => [severity, index])),
);

/** 按严重级别排序：未知级别排最后。 */
export function severityRank(severity: string): number {
  return SEVERITY_RANK[severity.toUpperCase()] ?? Number.MAX_SAFE_INTEGER;
}
