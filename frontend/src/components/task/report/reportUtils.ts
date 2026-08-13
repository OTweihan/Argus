/**
 * 报告 / 任务详情视图共用的纯函数与常量。
 *
 * 与 `frontend/src/utils.ts` 的 `formatDate` 命名区分：此处使用
 * `Intl.DateTimeFormat` + `zh-CN` locale 输出 `2026/05/14 09:46:00` 风格的串，
 * 与 ReportView / LLMDebugTab 历史输出保持一致，不与列表页的 `YYYY-MM-DD HH:mm:ss`
 * 共用以避免 UI 视觉漂移。
 *
 * 从 ReportView.vue 抽出 `REPORT_NAV_ITEMS` / `getStatusLabel` 等，
 * 减少 view 文件体积、便于单元测试。
 */
const DATE_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function formatReportDate(value: string | null): string {
  if (!value) return "-";
  try {
    return DATE_FORMATTER.format(new Date(value));
  } catch {
    return value;
  }
}

// JSON 格式化与时间线共用（./timeFormat），保持 re-export 以免改动既有调用点。
export { prettyJson } from "../timeFormat";

/** 黑盒报告页签条目，顺序与 `ReportView.vue` 中的内容面板一一对应。 */
export interface ReportNavItem {
  id: string;
  label: string;
  index: string;
}

export const REPORT_NAV_ITEMS: ReadonlyArray<ReportNavItem> = Object.freeze([
  { id: "overview", label: "概览", index: "01" },
  { id: "steps", label: "执行步骤", index: "02" },
  { id: "findings", label: "问题清单", index: "03" },
  { id: "raw-json", label: "原始 JSON", index: "04" },
]);

const STATUS_LABEL_MAP: Readonly<Record<string, string>> = Object.freeze({
  completed: "已完成",
  failed: "失败",
  timeout: "超时",
  cancelled: "已取消",
  running: "运行中",
  pending: "等待中",
});

/** 把任务状态枚举翻译为中文显示文案；未知状态原样返回。 */
export function getStatusLabel(status: string | null | undefined): string {
  if (!status) return "";
  return STATUS_LABEL_MAP[status] ?? status;
}

const DEFAULT_REPORT_SUMMARY = "未记录结果摘要。";

/**
 * 给定 report 对象推导 summary 文案：优先用 ``report.summary``、其次
 * ``report.task.resultSummary``，最后回落到默认提示。
 *
 * 该函数容忍 ``null`` / 空对象，便于在 ``computed`` 与 SSR 占位中复用。
 */
export function getReportSummary(
  report:
    | {
        summary?: string | null;
        task?: { resultSummary?: string | null } | null;
      }
    | null
    | undefined,
): string {
  if (!report) return DEFAULT_REPORT_SUMMARY;
  return report.summary || report.task?.resultSummary || DEFAULT_REPORT_SUMMARY;
}
