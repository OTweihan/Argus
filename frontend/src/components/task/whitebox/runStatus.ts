/** 白盒分析运行状态（AnalysisRunStatus）→ 中文文案 / el-tag 类型的共享映射。 */

const STATUS_LABELS: Record<string, string> = {
  QUEUED: "排队中",
  SUBMITTING: "提交中",
  RUNNING: "运行中",
  SUCCEEDED: "成功",
  FAILED: "失败",
  TIMED_OUT: "超时",
  CANCELLED: "已取消",
  STOPPED_WAITING: "已停止等待",
};

export type RunStatusTagType = "success" | "danger" | "warning" | "info";

export function runStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function runStatusTagType(status: string): RunStatusTagType {
  switch (status) {
    case "SUCCEEDED":
      return "success";
    case "FAILED":
    case "TIMED_OUT":
      return "danger";
    case "RUNNING":
    case "SUBMITTING":
      return "warning";
    default:
      return "info";
  }
}
