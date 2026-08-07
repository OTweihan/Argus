/**
 * 任务视图共用的短时间 / JSON 格式化纯函数。
 *
 * 时间线（timelineFormat）与 LLM trace（traceFormat）此前各自维护一份相同的
 * `Intl.DateTimeFormat` 格式化逻辑，统一收敛到此处以避免漂移。formatter 在
 * 模块级提升，避免每行渲染重复构造。
 */

const TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** zh-CN 短时间格式（MM-DD HH:mm:ss）。非法时间原样返回。 */
export function formatTime(iso: string): string {
  if (!iso) return "-";
  try {
    return TIME_FORMATTER.format(new Date(iso));
  } catch {
    return iso;
  }
}

export function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}
