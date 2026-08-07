import type { TimelineEvent } from "../../types";

const PHASE_COLORS: Record<string, string> = {
  task: "#3b82f6",
  browser: "#10b981",
  planner: "#f59e0b",
  executor: "#6b8a9e",
  evaluator: "#ef4444",
  report: "#0abab5",
  whitebox: "#8b5cf6",
};

const PHASE_LABELS: Record<string, string> = {
  task: "任务",
  browser: "浏览器",
  planner: "规划器",
  executor: "执行器",
  evaluator: "评估器",
  report: "报告",
  whitebox: "白盒分析",
};

const EVENT_TYPE_LABELS: Record<string, string> = {
  start: "开始",
  open_url: "打开 URL",
  snapshot: "页面快照",
  planner_start: "规划开始",
  planner_result: "规划结果",
  action: "执行动作",
  evaluator_start: "评估开始",
  evaluator_result: "评估结果",
  report: "报告生成",
  complete: "完成",
  fail: "失败",
  whitebox_source_resolved: "源码已准备",
  whitebox_source_validated: "源码校验通过",
  whitebox_submitted: "分析作业已提交",
  whitebox_progress: "分析进度",
  whitebox_succeeded: "分析完成",
  whitebox_failed: "分析失败",
  whitebox_cancelled: "分析已取消",
  whitebox_timed_out: "分析超时",
  whitebox_interrupted: "分析已中断",
};

export type WhiteboxLogLevel = "INFO" | "SUCCESS" | "WARN" | "ERROR";

const WHITEBOX_STAGE_LABELS: Record<string, string> = {
  source: "SOURCE",
  job: "JOB",
  classpath: "MAVEN",
  cache: "CACHE",
  analyzer: "ANALYZER",
};

const WHITEBOX_EVENT_STAGES: Record<string, string> = {
  whitebox_source_resolved: "source",
  whitebox_source_validated: "source",
  whitebox_submitted: "job",
  whitebox_succeeded: "analyzer",
  whitebox_failed: "analyzer",
  whitebox_cancelled: "analyzer",
  whitebox_timed_out: "analyzer",
  whitebox_interrupted: "analyzer",
};

export function phaseColor(phase: string): string {
  return PHASE_COLORS[phase] || "#909399";
}

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] || phase;
}

export function eventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABELS[eventType] || eventType;
}

export function whiteboxLogLevel(event: TimelineEvent): WhiteboxLogLevel {
  const remoteLevel = event.data?.level;
  if (typeof remoteLevel === "string") {
    const normalized = remoteLevel.toUpperCase();
    if (normalized === "ERROR") return "ERROR";
    if (normalized === "WARN" || normalized === "WARNING") return "WARN";
  }
  if (event.eventType === "whitebox_succeeded") return "SUCCESS";
  if (event.eventType === "whitebox_cancelled" || event.eventType === "whitebox_interrupted") {
    return "WARN";
  }
  if (event.eventType === "whitebox_failed" || event.eventType === "whitebox_timed_out") {
    return "ERROR";
  }
  return "INFO";
}

export function whiteboxLogStage(event: TimelineEvent): string {
  const remoteStage = event.data?.stage;
  const stage =
    typeof remoteStage === "string" && remoteStage
      ? remoteStage
      : (WHITEBOX_EVENT_STAGES[event.eventType] ?? event.phase);
  return WHITEBOX_STAGE_LABELS[stage] ?? stage.toUpperCase();
}

export function hasTimelineData(data: Record<string, unknown>): boolean {
  return data != null && typeof data === "object" && Object.keys(data).length > 0;
}

export function formatTimelineTime(iso: string): string {
  if (!iso) return "-";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function prettyTimelineJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function isTimelineEvent(raw: unknown): raw is TimelineEvent {
  if (!raw || typeof raw !== "object") return false;
  const value = raw as Record<string, unknown>;
  return typeof value.eventId === "string" && typeof value.taskId === "string";
}
