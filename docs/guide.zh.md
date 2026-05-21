# Argus 用户操作手册

[English](guide.md)

本手册涵盖有效使用 Argus 所需的全部内容——从配置和 Web 控制台到 Prompt 扩展、报告解读和故障排查。

---

## 目录

1. [配置](#配置)
2. [Web 控制台](#web-控制台)
3. [Prompt 扩展系统](#prompt-扩展系统)
4. [浏览器登录态管理](#浏览器登录态管理)
5. [报告与执行流程](#报告与执行流程)
6. [任务可观测性](#任务可观测性)
7. [最佳实践](#最佳实践)
8. [故障排查](#故障排查)

---

## 配置

### 大模型配置

Argus 需要兼容 OpenAI Chat Completions 的大模型 API。通过交互式命令配置：

```bash
argus config llm
```

配置保存在 `config/llm.env`——该文件已排除出版本控制。切勿提交此文件。

验证连通性：

```bash
argus llm check
```

#### 环境文件格式

```env
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

#### 高级参数

```bash
argus config llm --advanced
```

额外设置：最大输出 Token 数（默认 4096）、温度（默认 0）、最大重试次数（默认 3）。

### 服务器配置

服务器配置位于 `config/server.yaml`：

- **CORS 域名** — 允许的前端域名
- **限流** — 按路由限流
- **SSRF 防护** — 允许的私网 LLM 主机
- **可观测性** — 请求日志、审计、LLM 追踪开关
- **调度并发** — 最大并发任务数（默认 4）
- **WebSocket 限制** — 每事件总线最大订阅数

修改文件后重启 `argus serve` 生效。

### 模型配置（通过 Web 控制台）

可将多个 LLM 提供商配置存储在 SQLite 中，API Key 加密存储：

1. 在 Web 控制台中导航到**模型配置**
2. 点击**添加模型**，输入 API 地址、模型名称和 API Key
3. 点击**测试连接**验证
4. 创建任务时选择此模型配置

API Key 使用 Fernet 密钥加密存储，密钥位于 `config/.fernet_key`。首次启动 `argus serve` 时自动生成。

---

## Web 控制台

Web 控制台是 Vue 3 SPA，运行 `argus serve` 后访问 `http://localhost:8000/`。

### 构建前端

前端源码位于 `frontend/`。首次启动前需要构建：

```bash
cd frontend
pnpm install
pnpm build
cd ..
argus serve
```

初始构建后：
- 仅改 Python → 直接重启 `argus serve`，无需重新构建
- 改前端代码 → 再次运行 `pnpm build`，然后重启 `argus serve`

### 页面

#### 仪表盘

显示项目和最近任务的概览及状态。

#### 项目管理

管理测试项目。每个项目可以有：
- 名称和描述
- 自定义 Prompt 扩展（参见 [Prompt 扩展系统](#prompt-扩展系统)）
- 关联的任务

#### 任务管理

任务管理中心。功能：

- **创建任务** — 设置目标、URL、关联项目、模型配置和 Prompt 扩展
- **任务列表** — 按状态、项目筛选，按目标搜索
- **任务详情** — 三个页签：

  **报告页签** — 内联展示 HTML 报告，步骤和截图可折叠，问题清单清晰可见。

  **执行时间线页签** — 查看完整生命周期：任务创建 → 入队 → 启动 → 每个 Planner/Executor/Evaluator 循环 → 完成。事件通过 WebSocket 实时推送，持久化存储在 SQLite 的 `task_events` 表。

  **LLM 调试页签** — 检查任务期间的每次 LLM 调用：
  - 阶段、事件类型、模型、主机、耗时、Token 用量
  - System Prompt
  - 输入 Payload（完整 API 请求）
  - 原始响应（完整 API 响应）
  - 解析结果（JSON 提取后的结构化输出）
  - 错误和解析失败

#### 模型配置

管理 LLM 提供商配置。

---

## Prompt 扩展系统

Argus 将内置 Prompt 与用户自定义业务规则分离。

### 架构

```
拼接顺序：内置模板 → 项目扩展 → 任务扩展
```

- **内置模板**（`argus_py/llm/prompts/`）— 包含输入字段、输出 JSON Schema 和安全边界的硬契约，**不可覆盖**
- **项目扩展** — 存储在项目 `parameters.prompt_extensions.{planner,evaluator}` 中的自定义规则
- **任务扩展** — 存储在任务 `parameters.prompt_extensions.{planner,evaluator}` 中的自定义规则，拼接在项目扩展之后

内置模板末尾的 `## 业务扩展` / `## Business Extensions` 标记段即为扩展插入点。

### 通过 CLI 使用

```bash
argus run --goal "..." --url "..." \
  --planner-extension ./my-rules/planner.md \
  --evaluator-extension ./my-rules/evaluator.md
```

### 通过 Web 控制台使用

在项目或任务的创建/编辑对话框中，展开 **Prompt 业务扩展** 折叠面板：

- 两个 Tab：**Planner** 和 **Evaluator**
- 左侧 Markdown 编辑，右侧实时渲染
- 底部的**预览完整 Prompt**按钮调用 `POST /api/v1/prompts/preview`（600ms 防抖），展示内置 + 项目 + 任务三段拼接后的最终 Prompt

### 扩展示例

**Planner 扩展**（针对特定应用）：
```markdown
## 项目特定规则
- 危险按钮关键词：作废、出库、开账
- 登录页固定为 /auth/signin
- 不要点击 class 为 "disabled" 的元素
```

**Evaluator 扩展**：
```markdown
## 评估规则
- "成功"通知必须包含绿色勾选图标
- 登录后页面标题必须包含"仪表盘"
```

---

## 浏览器登录态管理

需要测试登录后页面时，可以一次保存登录态，跨任务复用。

### 保存登录态

```bash
argus auth save --url "https://example.com/login"
```

该命令显示浏览器窗口。手动登录后回到终端按 Enter，状态（cookies、localStorage、sessionStorage）保存到 `config/browser-states/<name>.json`。

### 列出已保存的登录态

```bash
argus auth list
```

### 复用登录态

```bash
argus run --auth-state example.com \
  --goal "检查个人中心页面是否正常展示" \
  --url "https://example.com/profile"
```

`--auth-state` 参数接受状态名称（在 `config/browser-states/` 中查找）或 JSON 文件路径。

> 登录态包含会话凭据。已通过 `.gitignore` 排除，但仍应按敏感文件对待——不要分享包含登录态的调试包。

---

## 报告与执行流程

### 执行流程

1. **Planner（LLM）** 接收测试目标和页面快照，决定下一步浏览器动作
2. **Executor** 通过 Playwright 执行动作，采集截图和 DOM 快照
3. **Evaluator（LLM）** 评估目标是否达成
4. 若未达成，携带更新后的上下文回到步骤 1
5. 动作失败时，恢复机制重新观察页面并重新规划（最多 2 次重试）
6. 完成后（成功或用尽所有尝试）生成 HTML + JSON 报告

### 报告输出

```
outputs/reports/<task_id>/
├── index.html      # 面向人工阅读的 HTML 报告
└── report.json     # 结构化 JSON 报告
```

**HTML 报告特性：**
- 任务摘要、执行步骤、步骤参数、截图、问题清单和错误信息
- 失败步骤高亮显示
- 步骤参数和截图可折叠
- 截图可点击放大
- 截图尽量使用相对路径引用

**JSON 报告**包含相同数据的结构化版本，适合下游工具或 API 读取。

### 报告 API

```
GET /api/v1/tasks/{task_id}/report    → HTML（默认）或 JSON（?format=json）
```

### 截图

默认每个执行步骤都会截图。存储在：

```
outputs/screenshots/<task_id>/
```

通过 `--no-screenshot` 关闭。关闭后，即使规划器输出 `screenshot` 动作，也只会记录"截图已按任务配置跳过"，不会保存图片。

---

## 任务可观测性

Argus 为任务执行提供丰富的可观测能力。

### 执行时间线

每个任务生命周期事件都记录在 SQLite 的 `task_events` 表中：
- 任务创建、入队、启动、完成
- 每个 Planner/Executor/Evaluator 循环
- 浏览器动作及其结果
- 报告生成

通过 API 获取：

```
GET /api/v1/tasks/{task_id}/events
```

或在 Web 控制台的**执行时间线**页签中查看（通过 WebSocket 实时更新）。

### LLM 调用追踪

每次 LLM 调用（Planner 和 Evaluator）都记录完整上下文：

- 阶段、事件类型、模型、主机、耗时、Token 用量
- 完整 System Prompt
- 输入 Payload（API 请求体）
- 原始响应（API 响应体）
- 解析结果（JSON 提取后）
- 错误和解析失败

存储为 JSONL：

```
outputs/traces/<task_id>.jsonl
```

通过 API 获取：

```
GET /api/v1/tasks/{task_id}/llm-traces          → 追踪概要列表
GET /api/v1/tasks/{task_id}/llm-traces/{trace_id} → 单条追踪详情
```

### 调试包

下载包含离线分析所需所有内容的 ZIP 包：

```
GET /api/v1/tasks/{task_id}/debug-bundle
```

包含：
- `task.json` — 完整任务数据
- `traces/llm.jsonl` — 所有 LLM 调用追踪
- `traces/events.jsonl` — 所有时间线事件
- 任务截图

### 敏感数据脱敏

所有日志、追踪和调试包都经过基于字段名的递归脱敏处理：
- 字段名匹配 `api_key`、`apikey`、`authorization`、`cookie`、`password`、`secret`、`token` → 值替换为 `***`
- URL 查询参数中的敏感名称也会被脱敏
- LLM 追踪内容还使用正则脱敏处理内联凭据（`sk-...`、JWT、内联 `key=value`）
- Token 用量统计（`token_usage`）属于白名单，不会被误打码

脱敏基于字段名匹配，不会扫描普通文本内容。

---

## 最佳实践

### 编写测试目标

- **具体明确：** "用空字段和错误密码测试登录表单" 优于 "测试登录"
- **描述预期结果：** "验证表单提交后出现成功消息"
- **一次一个目标：** 每个任务聚焦一个功能或流程
- **包含边界情况：** 对于表单，提及校验、必填字段、错误状态

### CLI 与 Web 控制台的选择

| 场景 | 推荐 |
|------|------|
| 快速一次性测试 | CLI `argus run` |
| 频繁回归检查 | CLI 配合登录态复用 |
| 管理大量项目 | Web 控制台 |
| 排查失败原因 | Web 控制台（时间线 + LLM 调试） |
| 团队协作 | Web 控制台 + 共享模型配置 |

### 优化 LLM 成本

- 复用登录态，避免重复登录步骤
- 为简单任务设置合理的 `--max-steps` 和 `--timeout`
- 使用 `--create-only` 创建任务模板，需要时才执行
- 在 Web 控制台查看 LLM 追踪，识别不必要的调用

### 安全

- 切勿提交 `config/llm.env` 或 `config/browser-states/`
- 调试包可能包含敏感信息（页面内容和 LLM 输入）
- 生产部署时启用 API Token 认证和限流
- 配置 SSRF 防护，保护私网 LLM 端点

---

## 故障排查

### LLM 连接问题

| 现象 | 可能原因 | 解决方法 |
|------|---------|----------|
| `argus llm check` 超时 | API 地址错误或网络问题 | 检查 `config/llm.env`，确认网络可达 |
| "401 Unauthorized" | API Key 无效 | 运行 `argus config llm` 重新输入 |
| "Model not found" | 模型名称错误 | 查阅提供商文档确认正确的模型 ID |
| "SSRF blocked" | 私网主机未加入白名单 | 在 `config/server.yaml` → `llm.allow_private_hosts` 中添加主机 |

### 浏览器问题

| 现象 | 可能原因 | 解决方法 |
|------|---------|----------|
| "Browser not found" | 未安装 Playwright 浏览器 | 运行 `playwright install chromium` |
| 截图为空白 | 页面未完全加载或需要认证 | 检查 URL 可访问性，使用 `--headed` 调试 |
| 找不到选择器 | DOM 变化或选择器错误 | 运行 `argus browser check` 检查页面 |
| 无头模式失败 | 缺少系统依赖 | 使用 `--headed` 或安装 Playwright 系统库 |

### 任务执行

| 现象 | 可能原因 | 解决方法 |
|------|---------|----------|
| 任务不断重试 | 动作持续失败 | 在 LLM 调试页签查看规划器决策 |
| 任务完成但目标未达成 | 评估器误判 | 添加评估器 Prompt 扩展，明确判断标准 |
| 报告缺少截图 | 使用了 `--no-screenshot` | 不使用此标志重新执行 |
| WebSocket 断开 | 服务器重启或达到订阅上限 | 检查服务器日志，调整 `events.max_subscribers` |
