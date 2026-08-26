/** 诊断中心视图共享工具：格式化与选项常量。 */

export const COMPONENT_OPTIONS = [
  { value: "", label: "全部组件" },
  { value: "python", label: "Python" },
  { value: "java", label: "Java" },
  { value: "frontend", label: "前端" },
] as const;

export const LEVEL_OPTIONS = [
  { value: "", label: "全部级别" },
  { value: "DEBUG", label: "DEBUG" },
  { value: "INFO", label: "INFO" },
  { value: "WARN", label: "WARN" },
  { value: "ERROR", label: "ERROR" },
  { value: "CRITICAL", label: "FATAL" },
] as const;

export function levelTagType(
  level: string,
): "success" | "info" | "warning" | "danger" {
  switch (level.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
    case "FATAL":
      return "danger";
    case "WARN":
    case "WARNING":
      return "warning";
    default:
      return "info";
  }
}

export function formatTimestamp(iso: string): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 时 ${minutes} 分`;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
