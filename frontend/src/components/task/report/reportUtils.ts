/**
 * 报告 / 任务详情视图共用的格式化函数。
 *
 * 与 `frontend/src/utils.ts` 的 `formatDate` 略有差异：此处使用
 * `Intl.DateTimeFormat` + `zh-CN` locale 输出 `2026/05/14 09:46:00` 风格的串，
 * 与 ReportView / LLMDebugTab 历史输出保持一致，不与列表页的 `YYYY-MM-DD HH:mm:ss`
 * 共用以避免 UI 视觉漂移。
 */
export function formatDate(value: string | null): string {
    if (!value) return "-";
    try {
        return new Intl.DateTimeFormat("zh-CN", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        }).format(new Date(value));
    } catch {
        return value;
    }
}

export function prettyJson(value: unknown): string {
    return JSON.stringify(value, null, 2);
}
