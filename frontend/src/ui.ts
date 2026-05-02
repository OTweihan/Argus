import type { ViewKey } from "./state";

export function navButton(currentView: ViewKey, view: ViewKey, label: string): string {
  return `<button class="${currentView === view ? "active" : ""}" data-view="${view}">${label}</button>`;
}

export function viewTitle(view: ViewKey): string {
  return {
    dashboard: "仪表盘",
    projects: "项目管理",
    tasks: "任务管理",
    models: "模型配置",
  }[view];
}

export function eventStatusText(status: string): string {
  return status === "connected" ? "已连接" : status === "error" ? "异常" : "未连接";
}

export function metric(label: string, value: number): string {
  return `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`;
}

export function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function compact(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char] ?? char;
  });
}

export function showDialog(title: string, message: string, tone: "success" | "error" | "info"): void {
  closeDialog();
  const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const dialog = document.createElement("div");
  dialog.className = "dialog-backdrop";
  dialog.innerHTML = `
    <div class="dialog ${tone}" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
      <div class="dialog-header">
        <h2 id="dialog-title">${escapeHtml(title)}</h2>
        <button type="button" data-action="close-dialog" aria-label="关闭">×</button>
      </div>
      <div class="dialog-body">${escapeHtml(message).replace(/\n/g, "<br />")}</div>
      <div class="dialog-actions">
        <button class="primary" type="button" data-action="close-dialog">确定</button>
      </div>
    </div>
  `;
  dialog.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    if (target === dialog || target.closest("[data-action='close-dialog']")) {
      closeDialog();
    }
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDialog();
      previouslyFocused?.focus();
    }
  });
  document.body.appendChild(dialog);
  dialog.querySelector<HTMLButtonElement>("[data-action='close-dialog']")?.focus();
}

export function closeDialog(): void {
  document.querySelector(".dialog-backdrop")?.remove();
}
