import { reportUrl } from "./api";
import { state } from "./state";
import type { ModelConfig, Project, Task } from "./types";
import { compact, escapeHtml, formatDate, metric } from "./ui";

export function renderDashboard(): string {
  const running = state.allTasks.filter((task) => task.status === "running").length;
  const findings = state.allTasks.reduce((total, task) => total + task.findings.length, 0);
  const recentTasks = [...state.allTasks]
    .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
    .slice(0, 8);
  return `
    <section class="grid metrics">
      ${metric("项目", state.projects.length)}
      ${metric("任务", state.allTasks.length)}
      ${metric("运行中", running)}
      ${metric("问题", findings)}
    </section>
    <section class="panel" style="margin-top:14px">
      <h2>最近任务</h2>
      ${taskTable(recentTasks)}
    </section>
  `;
}

export function renderProjects(): string {
  return `
    <section class="grid two">
      <div class="panel">
        <h2>项目配置</h2>
        <form id="project-form" class="form-grid">
          <div class="field"><label>名称</label><input name="name" required /></div>
          <div class="field"><label>描述</label><textarea name="description"></textarea></div>
          <div class="field"><label>基础 URL</label><input name="baseUrl" placeholder="https://example.com" /></div>
          <div class="field"><label>Git URL</label><input name="gitUrl" /></div>
          <div class="field"><label>登录态名称</label><input name="authStateName" /></div>
          <div class="form-grid two">
            <div class="field"><label>默认最大步骤</label><input name="defaultMaxSteps" type="number" min="1" /></div>
            <div class="field"><label>默认超时秒数</label><input name="defaultTimeoutSeconds" type="number" min="1" /></div>
          </div>
          <div class="checks"><label><input name="defaultCaptureScreenshots" type="checkbox" checked /> 截图</label></div>
          <div class="field"><label>参数 JSON</label><textarea name="parameters">{}</textarea></div>
          <div class="actions">
            <button class="primary" type="submit">保存项目</button>
            <button type="button" data-action="reset-project-form">清空</button>
          </div>
        </form>
      </div>
      <div class="panel">
        <h2>项目列表</h2>
        ${projectTable(state.projects)}
      </div>
    </section>
  `;
}

export function renderTasks(): string {
  const selected =
    state.allTasks.find((task) => task.taskId === state.selectedTaskId) ??
    state.visibleTasks[0] ??
    null;
  return `
    <section class="grid two">
      <div class="panel">
        <h2>创建任务</h2>
        <form id="task-form" class="form-grid">
          <div class="field"><label>项目</label><select name="projectId" required>${projectOptions()}</select></div>
          <div class="field"><label>目标</label><textarea name="goal" required></textarea></div>
          <div class="field"><label>起始 URL</label><input name="startUrl" /></div>
          <div class="form-grid two">
            <div class="field"><label>最大步骤</label><input name="maxSteps" type="number" min="1" /></div>
            <div class="field"><label>超时秒数</label><input name="timeoutSeconds" type="number" min="1" /></div>
          </div>
          <div class="field"><label>模型配置</label><select name="modelConfigId">${modelOptions()}</select></div>
          <div class="checks"><label><input name="captureScreenshots" type="checkbox" checked /> 截图</label></div>
          <div class="field"><label>参数 JSON</label><textarea name="parameters">{}</textarea></div>
          <div class="actions"><button class="primary" type="submit">创建任务</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>任务列表</h2>
        <div class="actions" style="margin-bottom:10px">
          <select id="task-filter-status" data-filter>
            <option value="">全部状态</option>
            ${["pending", "running", "completed", "failed", "timeout", "cancelled"]
              .map(
                (status) =>
                  `<option value="${status}" ${state.taskStatusFilter === status ? "selected" : ""}>${status}</option>`,
              )
              .join("")}
          </select>
          <select id="task-filter-project" data-filter>
            <option value="">全部项目</option>
            ${projectOptions(state.taskProjectFilter)}
          </select>
        </div>
        ${taskTable(state.visibleTasks)}
      </div>
    </section>
    <section class="panel" style="margin-top:14px">
      <h2>任务详情</h2>
      ${selected ? taskDetail(selected) : `<div class="empty">暂无任务。</div>`}
    </section>
  `;
}

export function renderModels(): string {
  return `
    <section class="grid two">
      <div class="panel">
        <h2>模型配置</h2>
        <form id="model-form" class="form-grid">
          <div class="field"><label>名称</label><input name="name" required /></div>
          <div class="form-grid two">
            <div class="field"><label>供应商</label><select name="provider">${providerOptions()}</select></div>
            <div class="field"><label>模型</label><input name="model" required /></div>
          </div>
          <div class="field"><label>API Key</label><input name="apiKey" type="password" autocomplete="new-password" /></div>
          <div class="field"><label>Base URL</label><input name="baseUrl" /></div>
          <div class="field"><label>Completions Path</label><input name="completionsPath" value="/chat/completions" /></div>
          <div class="form-grid two">
            <div class="field"><label>最大 Token</label><input name="maxTokens" type="number" min="1" value="4096" /></div>
            <div class="field"><label>温度</label><input name="temperature" type="number" min="0" step="0.01" value="0.1" /></div>
          </div>
          <div class="form-grid two">
            <div class="field"><label>重试次数</label><input name="maxRetries" type="number" min="0" value="3" /></div>
            <div class="field"><label>超时秒数</label><input name="timeoutSeconds" type="number" min="1" value="60" /></div>
          </div>
          <div class="field"><label>任务类型默认</label><select name="taskType">${taskTypeOptions()}</select></div>
          <div class="checks">
            <label><input name="isDefault" type="checkbox" /> 默认</label>
            <label><input name="enabled" type="checkbox" checked /> 启用</label>
          </div>
          <div class="actions">
            <button class="primary" type="submit">保存模型</button>
            <button type="button" data-action="test-model">测试</button>
            <button type="button" data-action="reset-model-form">清空</button>
          </div>
        </form>
      </div>
      <div class="panel">
        <h2>模型列表</h2>
        ${modelTable(state.models)}
      </div>
    </section>
  `;
}

function projectTable(projects: Project[]): string {
  if (!projects.length) return `<div class="empty">暂无项目。</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>名称</th><th>基础 URL</th><th>默认值</th><th>更新时间</th><th>操作</th></tr></thead>
        <tbody>
          ${projects
            .map(
              (project) => `
                <tr>
                  <td><strong>${escapeHtml(project.name)}</strong><div class="muted mono">${project.projectId}</div></td>
                  <td>${escapeHtml(project.baseUrl ?? "-")}</td>
                  <td>${project.defaultMaxSteps ?? "-"} 步 / ${project.defaultTimeoutSeconds ?? "-"} 秒</td>
                  <td>${formatDate(project.updatedAt)}</td>
                  <td class="actions">
                    <button data-action="edit-project" data-id="${project.projectId}">编辑</button>
                    <button class="danger" data-action="delete-project" data-id="${project.projectId}">删除</button>
                  </td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function taskTable(tasks: Task[]): string {
  if (!tasks.length) return `<div class="empty">暂无任务。</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>目标</th><th>状态</th><th>项目</th><th>步骤</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody>
          ${tasks
            .map(
              (task) => `
                <tr>
                  <td><strong>${escapeHtml(compact(task.goal, 52))}</strong><div class="muted mono">${task.taskId}</div></td>
                  <td><span class="pill ${task.status}">${task.status}</span></td>
                  <td>${escapeHtml(projectName(task.projectId))}</td>
                  <td>${task.currentStep}/${task.maxSteps}</td>
                  <td>${formatDate(task.createdAt)}</td>
                  <td class="actions">
                    <button data-action="select-task" data-id="${task.taskId}">详情</button>
                    <button class="primary" data-action="start-task" data-id="${task.taskId}" ${
                      task.status === "pending" ? "" : "disabled"
                    }>启动</button>
                  </td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function modelTable(models: ModelConfig[]): string {
  if (!models.length) return `<div class="empty">暂无模型配置。</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>名称</th><th>供应商</th><th>模型</th><th>作用域</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          ${models
            .map(
              (model) => `
                <tr>
                  <td><strong>${escapeHtml(model.name)}</strong><div class="muted mono">${model.modelConfigId}</div></td>
                  <td>${model.provider}</td>
                  <td>${escapeHtml(model.model)}</td>
                  <td>${model.taskType ?? "全局"}${model.isDefault ? " / 默认" : ""}</td>
                  <td>${model.enabled ? "启用" : "停用"} / Key ${model.apiKeySet ? "已配置" : "未配置"}</td>
                  <td class="actions">
                    <button data-action="edit-model" data-id="${model.modelConfigId}">编辑</button>
                    <button data-action="test-model" data-id="${model.modelConfigId}">测试</button>
                    <button class="danger" data-action="delete-model" data-id="${model.modelConfigId}">删除</button>
                  </td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function taskDetail(task: Task): string {
  const logs = task.logs.length
    ? task.logs
        .map(
          (log) => `
          <div class="item-card">
            <div class="item-title">
              <strong>#${log.stepNumber} ${escapeHtml(log.action)}</strong>
              <span class="pill ${log.result}">${log.result}</span>
            </div>
            <div class="muted">${escapeHtml(log.message ?? log.error ?? "")}</div>
            <div class="mono muted">${escapeHtml(log.urlAfter ?? log.urlBefore ?? "")}</div>
          </div>
        `,
        )
        .join("")
    : `<div class="empty">暂无日志。</div>`;
  const findings = task.findings.length
    ? task.findings
        .map(
          (finding) => `
          <div class="item-card">
            <div class="item-title">
              <strong>${escapeHtml(finding.title)}</strong>
              <span class="pill ${finding.severity}">${finding.severity}</span>
            </div>
            <div>${escapeHtml(finding.description)}</div>
            <div class="mono muted">${escapeHtml(finding.url ?? "")}</div>
          </div>
        `,
        )
        .join("")
    : `<div class="empty">暂无问题。</div>`;
  return `
    <div class="detail">
      <div class="actions">
        <span class="pill ${task.status}">${task.status}</span>
        <span class="mono">${task.taskId}</span>
        <a href="${reportUrl(task.taskId)}" target="_blank" rel="noreferrer"><button>HTML 报告</button></a>
        <a href="${reportUrl(task.taskId, true)}" target="_blank" rel="noreferrer"><button>JSON 报告</button></a>
      </div>
      <div><strong>${escapeHtml(task.goal)}</strong></div>
      <div class="muted">${escapeHtml(task.resultSummary ?? task.errorMessage ?? "")}</div>
      <div class="grid two">
        <div>
          <h2>步骤日志</h2>
          <div class="log-list">${logs}</div>
        </div>
        <div>
          <h2>问题</h2>
          <div class="finding-list">${findings}</div>
        </div>
      </div>
    </div>
  `;
}

function projectOptions(selectedProjectId = ""): string {
  return state.projects
    .map(
      (project) =>
        `<option value="${project.projectId}" ${
          selectedProjectId === project.projectId ? "selected" : ""
        }>${escapeHtml(project.name)}</option>`,
    )
    .join("");
}

function modelOptions(): string {
  return `<option value="">默认模型</option>${state.models
    .filter((model) => model.enabled)
    .map((model) => `<option value="${model.modelConfigId}">${escapeHtml(model.name)}</option>`)
    .join("")}`;
}

function providerOptions(): string {
  return ["dashscope", "openai", "ollama", "anthropic", "custom"]
    .map((provider) => `<option value="${provider}">${provider}</option>`)
    .join("");
}

function taskTypeOptions(): string {
  return `<option value="">全局默认</option><option value="blackbox">blackbox</option><option value="whitebox">whitebox</option>`;
}

function projectName(projectId: string | null): string {
  if (!projectId) return "-";
  return state.projects.find((project) => project.projectId === projectId)?.name ?? projectId;
}
