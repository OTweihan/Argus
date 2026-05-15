# Argus - AI Native Test Platform

> Every bug has nowhere to hide.

Argus 是一个面向 Web 应用质量保障场景的 AI Native 测试平台。当前阶段聚焦黑盒 MVP：用自然语言描述测试目标，由大模型规划浏览器动作，驱动 Playwright 执行，并输出结构化测试报告。

## 当前状态

当前处于平台化增强阶段，已完成 T001、T002、T003、T004、T005、T006、T007、T009、T010、T011、T012、T013、T014、T015 和 T016 的基础能力，并补齐了面向企业自用测试场景的任务可观测性能力：

- T001 项目骨架：Python 包结构、CLI 入口、任务模型、报告模型、配置边界、占位模块。
- T002 浏览器封装：Playwright 生命周期、浏览器动作、截图、页面快照、轻量调试命令。
- T003 LLM 调用模块：OpenAI Chat Completions 兼容调用、Prompt 模板、响应模型、JSON 解析、重试逻辑、交互式配置命令。
- T004 任务模型与执行边界：任务 JSON 反序列化、文件存储读取、任务查询、状态流转、步骤日志、问题记录和可注册任务执行器。
- T005 黑盒 Agent 主逻辑：LLM 动作规划、浏览器动作执行、页面快照观察、LLM 结果评估、步骤日志和问题记录闭环。
- T006 报告生成：根据任务结果生成 HTML 和 JSON 报告，并回写任务报告路径。
- T007 CLI 端到端联调：`argus run` 已接入任务创建、黑盒执行、失败恢复、每步截图、报告输出和失败状态回写。
- T009 FastAPI 骨架：新增 FastAPI 应用、健康检查、基础任务 REST API、路由包、中间件、服务配置和 `argus serve`。
- T010 项目管理模块：新增 Project 模型、SQLite 存储、CRUD 服务、项目 REST API，并要求 Web API 创建任务关联项目。
- T011 任务 REST API 完整化：补齐任务启动/暂停/终止语义端点，拆分报告路由，支持 HTML/JSON 报告读取。
- T012 异步任务调度：新增进程内任务队列和后台 Worker，`/tasks/{id}/start` 可入队并后台执行任务。
- T013 WebSocket 实时日志：新增进程内事件总线，推送任务状态、步骤日志、问题和完成事件。
- T014 模型配置管理：新增模型配置 SQLite 存储、REST API、连接检查和任务 `modelConfigId` 解析。
- T015 Web 控制台：采用 TypeScript + Vite + Vue 3 + Element Plus，前端源码位于 `frontend/`，构建产物由 FastAPI 托管。
- T016 端到端联调：新增自动化契约测试和手工验收测试用例，覆盖平台化主链路。
- 任务可观测性增强：任务详情支持报告、执行时间线和 LLM 调试三个页签；后端持久化任务时间线、记录 Planner / Evaluator 的 LLM 调用追踪，并提供调试包下载。

暂未完成：

- 运行中任务可靠中断、服务重启队列恢复、Java 白盒分析。

## 环境要求

- Windows 11
- PowerShell 7
- Python 3.11+
- Playwright 浏览器运行环境
- OpenAI Chat Completions 兼容的大模型 API

## 快速开始

在项目根目录执行：

```powershell
pip install -e ".[dev]"
argus --version
```

安装 Playwright Chromium：

```powershell
playwright install chromium
```

## Web 控制台构建产物

Web 控制台源码位于 `frontend/`，Vite 构建产物输出到 `argus_py/api/static/`，并由 FastAPI 在 `argus serve` 启动时托管。该目录会随 Python 包一起分发，目的是让本地部署在未安装 Node 依赖时也能直接打开控制台。

本仓库保留并提交 `argus_py/api/static/` 构建产物。修改 `frontend/src/` 中影响控制台运行效果的代码后，需要在 `frontend/` 下执行前端构建，并一并提交更新后的 `argus_py/api/static/`。不要手工修改 `argus_py/api/static/`，该目录内容只应由前端构建生成。

## 任务可观测性与调试

Web 控制台的任务详情页包含三个页签：

- 报告：展示 HTML/JSON 报告中的任务摘要、步骤、截图和问题。
- 执行时间线：展示任务生命周期、浏览器操作、Planner、Executor、Evaluator、报告生成等阶段事件；事件会写入 SQLite 的 `task_events` 表，并通过 WebSocket 实时刷新。
- LLM 调试：展示 Planner / Evaluator 的 LLM 调用追踪，包括阶段、事件、模型、Host、耗时、token 使用量、System Prompt、Input Payload、Raw Response、Parsed Result、错误和解析错误。

LLM 追踪默认写入：

```text
outputs/traces/<task_id>.jsonl
```

调试数据会按敏感 key 做递归脱敏，覆盖嵌套 dict 和 list 中的 `api_key`、`password`、`token` 等字段；`token_usage` 属于统计信息白名单，不会被误打码。当前脱敏策略主要基于字段名，不会扫描普通字符串内容。

相关 Web API：

| 场景 | API |
|------|-----|
| 获取任务时间线 | `GET /api/v1/tasks/{task_id}/events` |
| 获取 LLM 追踪列表 | `GET /api/v1/tasks/{task_id}/llm-traces` |
| 获取单条 LLM 追踪 | `GET /api/v1/tasks/{task_id}/llm-traces/{trace_id}` |
| 下载调试包 | `GET /api/v1/tasks/{task_id}/debug-bundle` |

调试包是 ZIP 文件，包含 `task.json`、`traces/llm.jsonl`、`traces/events.jsonl` 和任务截图目录中的图片，便于复现大模型输入输出和执行过程。

## CLI 常用命令

| 场景 | 命令 |
|------|------|
| 查看版本 | `argus --version` |
| 启动 Web API | `argus serve` |
| 指定 Web API 地址 | `argus serve --host 127.0.0.1 --port 8000` |
| 配置大模型 | `argus config llm` |
| 配置高级大模型参数 | `argus config llm --advanced` |
| 检查大模型连接 | `argus llm check` |
| 调大 LLM 检查等待时间 | `argus llm check --timeout 90` |
| 检查浏览器打开和截图 | `argus browser check --url "https://httpbin.org"` |
| 显示浏览器窗口调试 | `argus browser check --url "https://httpbin.org" --headed` |
| 保存浏览器登录态 | `argus auth save --url "https://example.com/login"` |
| 查看已保存登录态 | `argus auth list` |
| 执行黑盒任务 | `argus run --goal "打开页面并截图" --url "https://httpbin.org"` |
| 复用登录态执行任务 | `argus run --auth-state example.com --goal "检查个人中心" --url "https://example.com/profile"` |
| 显示浏览器窗口执行任务 | `argus run --goal "打开页面并截图" --url "https://httpbin.org" --headed` |
| 只创建任务快照 | `argus run --goal "打开页面并截图" --url "https://httpbin.org" --create-only` |
| 关闭步骤截图 | `argus run --goal "打开页面并检查标题" --url "https://httpbin.org" --no-screenshot` |

## 配置大模型

使用交互式命令配置：

```powershell
argus config llm
```

该命令会提示输入：

- API Key
- 接口地址
- 模型名称

API Key 输入时会显示星号掩码。配置会写入：

```text
config/llm.env
```

`config/llm.env` 不纳入版本控制，不要提交、复制或输出其中内容。

首次配置不会询问高级参数，默认使用内置值。需要调整最大输出 Token 数、温度、最大重试次数时执行：

```powershell
argus config llm --advanced
```

## 检查大模型连接

```powershell
argus llm check
```

该命令使用固定低消耗 Prompt 检查连接，不允许用户自由输入 Prompt，避免不必要的 token 消耗。

如果接口或代理响应较慢，可临时调大等待时间：

```powershell
argus llm check --timeout 90
```

临时覆盖模型或接口地址：

```powershell
argus llm check --model "qwen3.5-plus" --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## 检查浏览器能力

打开页面并截图：

```powershell
argus browser check --url "https://httpbin.org"
```

显示浏览器窗口：

```powershell
argus browser check --url "https://httpbin.org" --headed
```

指定截图路径：

```powershell
argus browser check --url "https://httpbin.org" --screenshot "outputs/screenshots/httpbin-check.png"
```

验证输入和点击：

```powershell
argus browser check --url "https://httpbin.org/forms/post" --fill-selector "input[name='custname']" --fill-text "WeiHan" --click "text=Submit"
```

浏览器封装会在系统层面等待页面稳定，常规情况下不需要手动增加等待。`--wait-ms` 仅作为额外调试参数。

## 保存和复用登录态

需要测试登录后的页面时，可以先用可视化浏览器完成一次登录，并保存 Playwright `storage_state`：

```powershell
argus auth save --url "https://example.com/login"
```

该命令默认显示浏览器窗口。完成登录后回到终端按 Enter，登录态会保存到：

```text
config/browser-states/example.com.json
```

如果需要自定义名称，也可以显式传入：

```powershell
argus auth save --name example-admin --url "https://example.com/login"
```

查看已保存登录态：

```powershell
argus auth list
```

后续执行黑盒任务时复用登录态：

```powershell
argus run --auth-state example.com --goal "检查个人中心页面是否正常展示" --url "https://example.com/profile"
```

`argus auth list` 会显示登录态名称、关联站点、修改时间、复用命令和文件路径。`--auth-state` 既可以传登录态名称，也可以传 JSON 文件路径。登录态文件包含 Cookie、LocalStorage 等会话信息，已通过 `.gitignore` 排除，仍应按敏感文件处理，不要提交或外发。

对于带端口的地址，Windows 文件名不支持冒号，登录态名称会把端口分隔符转换为 `-`，例如 `http://10.18.90.80:8580/system/user` 默认保存为 `config/browser-states/10.18.90.80-8580.json`。

## 执行黑盒任务

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

复杂流程可以直接用自然语言描述：

```powershell
argus run --goal "打开首页 → 点击链接 → 填写表单 → 提交 → 验证结果" --url "https://demo.playwright.dev/todomvc"
```

登录页或表单页建议把覆盖点写清楚：

```powershell
argus run --goal "全面测试登录界面，包括必填校验和错误登录提示" --url "https://example.com/login"
```

显示浏览器窗口执行：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --headed
```

只创建任务、不执行：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --create-only
```

执行完成后会输出任务状态、步骤数量、问题数量和 HTML 报告路径。报告默认写入：

```text
outputs/reports/<task_id>/index.html
outputs/reports/<task_id>/report.json
```

任务步骤、失败动作和最终结果会写入任务 JSON；默认每个执行步骤都会尽量保存截图，截图默认写入：

```text
outputs/screenshots/<task_id>/
```

不需要截图证据时可关闭：

```powershell
argus run --goal "打开页面并检查标题" --url "https://httpbin.org" --no-screenshot
```

关闭截图后，即使规划器输出 `screenshot` 动作，也只会记录“截图已按任务配置跳过”，不会保存图片。

`--max-steps` 和 `--timeout` 默认由系统根据任务描述自动分配；需要手动限制时仍可显式传入：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --max-steps 5 --timeout 180
```

当前自动分配策略：

| 任务类型 | 最大步数 | 超时 |
|----------|----------|------|
| 简单访问 / 截图 / 可访问性检查 | 6 | 180 秒 |
| 普通黑盒任务 | 12 | 300 秒 |
| 登录 / 表单 / 提交 / 流程类任务 | 20 | 600 秒 |

## 示例任务

`examples/` 目录保存当前任务模型的 JSON 示例，字段名与 `argus_py.task.models.Task` 保持一致：

```text
examples/task_001_screenshot.json
examples/task_002_multistep.json
```

这些文件用于说明任务数据结构，不是当前 CLI 的直接输入文件。当前执行任务请使用 `argus run --goal ... --url ...`，只需要保存任务快照时使用 `--create-only`。

## 报告说明

T007 阶段会在任务完成、失败或异常恢复后尽力生成报告，并把 HTML 报告路径回写到任务 JSON 的 `report_path` 字段。

报告产物默认位于：

```text
outputs/reports/<task_id>/index.html
outputs/reports/<task_id>/report.json
```

其中：

- `index.html` 是面向人工阅读的黑盒测试报告，包含任务信息、执行步骤、步骤参数、截图、问题清单和错误信息。
- `report.json` 是结构化报告，包含同一份任务、步骤和问题数据，便于后续 Web API 或前端读取。
- HTML 报告会聚合失败步骤，步骤参数和截图默认折叠，截图可点击放大预览。
- 步骤截图默认位于 `outputs/screenshots/<task_id>/`，报告会尽量使用相对路径展示图片。
- 如果执行时传入 `--no-screenshot`，报告仍会生成，但步骤里不会包含新保存的截图文件。
- 如果报告生成失败，系统不会覆盖原始任务结果，会把报告生成错误追加到任务错误信息中。

### 黑盒执行策略

- 初始动作由系统确定性打开起始 URL，后续动作由 LLM 基于页面快照和历史步骤规划。
- 每个成功或失败步骤都会尽量采集截图和页面快照，报告会展示步骤截图。
- 动作失败时不会立刻终止任务；系统会记录失败步骤、重新观察页面，并让规划器基于失败历史重新规划，默认最多恢复 2 次。
- 页面快照会给可交互元素生成推荐 selector，例如 `role=button[name="登录"]`、`css=[name="username"]`、`placeholder=请输入用户名`。
- 常见 LLM 误写的 `button:contains("登录")`、`a:contains("提交")` 会在选择器解析层自动转换为 Playwright 兼容定位。
- 对“测试登录界面”“测试表单”“测试页面功能”等目标，评估器不会仅因为元素存在就判定完成；需要看到实际输入、点击、提交、校验或错误提示等交互证据。

## 项目结构

```text
argus/
├── argus_py/
│   ├── cli/           # CLI 入口与交互提示文案
│   ├── api/           # 第二阶段 FastAPI 应用、路由、Schema、中间件、静态控制台托管
│   ├── core/          # 常量、路径、枚举、异常、ID
│   ├── config/        # Python 配置加载、模型配置服务和 SQLite 存储
│   ├── llm/           # LLM 调用、供应商适配、内置 Prompt、解析、重试
│   ├── observability/ # 审计、敏感信息脱敏、LLM 调用追踪
│   ├── task/          # 任务模型、状态、SQLite 存储、时间线事件和服务
│   ├── blackbox/      # 黑盒 Agent 规划、评估、执行边界
│   ├── browser/       # Playwright 生命周期、动作、选择器、快照
│   ├── report/        # 报告模型、序列化、HTML/JSON 导出
│   ├── project/       # 第二阶段项目模型、SQLite 存储和 CRUD 服务
│   ├── infra/         # SQLite 基础设施；后续扩展缓存、队列
│   ├── whitebox/      # 第三阶段 Java 白盒分析客户端占位
│   └── utils/         # 通用工具
├── config/
│   ├── llm.env        # 本地大模型配置，不提交
│   ├── llm.env.example
│   └── logging.yaml
├── frontend/          # TypeScript + Vite 控制台源码
├── docs/
│   └── project-info/  # 项目上下文、变更、问题、待办
├── outputs/           # 运行产物，内容不纳入版本控制
├── tests/             # 单元测试、契约测试和边界测试
├── examples/          # 示例任务 JSON 与说明
├── scripts/           # 开发脚本占位
└── java_analyzer/     # 第三阶段 Java 白盒分析子模块占位
```

## Prompt 模板

Prompt 模板分为**内置模板**和**用户业务扩展**两部分：

- 内置模板位于 `argus_py/llm/prompts/`，随 Python 包一起发布；包含输入字段、输出 JSON schema 和安全边界等硬契约，**不可覆盖**。
- 当前内置模板：

  ```text
  blackbox_planner.md
  blackbox_evaluator.md
  ```

  内置模板末尾保留 `## 业务扩展` marker 段，用户扩展会拼接到这里之后。

- `argus llm check` 使用的连接检查 Prompt 已内联在 CLI 代码中，不属于模板体系。

### 用户业务扩展（项目 + 任务双层）

用户可以为每个**项目**或**任务**追加业务规则，拼接顺序为 `内置 → 项目扩展 → 任务扩展`。

存储位置：复用现有 `Project.parameters` / `Task.parameters` 字典，约定 key 为 `prompt_extensions`：

```json
{
  "prompt_extensions": {
    "planner": "## 项目特定规则\n- 危险按钮关键词：作废、出库、开账\n- 登录页固定在 /auth/signin",
    "evaluator": "..."
  }
}
```

任务级扩展可以通过 CLI 在创建任务时指定：

```pwsh
argus run --goal "..." --url "..." `
  --planner-extension .\prompt-ext\planner.md `
  --evaluator-extension .\prompt-ext\evaluator.md
```

**前端控制台**：在 Web 控制台的「项目新增/编辑」与「任务新增/编辑」对话框中，展开折叠面板 **Prompt 业务扩展**，即可在 Planner / Evaluator 两个 Tab 下用双栏（左侧 Markdown 编辑、右侧实时渲染）的方式编辑扩展内容；面板底部的「完整 system_prompt 预览」会以 600ms 防抖调用后端 `POST /api/v1/prompts/preview`，展示内置 + 项目 + 任务三段拼接后的最终 Prompt。项目详情和任务详情对话框也会以只读 Markdown 展示已配置的扩展内容。

> **迁移提示**：旧版本曾支持把 `config/prompts/<name>.md` 作为用户全覆盖模板，本版本已**移除该机制**。如果你之前有自定义文件，请把内容迁移到对应项目或任务的 `parameters.prompt_extensions.{planner,evaluator}`。

## 路径策略

项目通过 `argus_py/core/paths.py` 统一解析路径：

- 默认从项目根目录读取 `config/llm.env` 和 `outputs`；内置 Prompt 和报告模板从包内读取。
- 从其他目录执行 `argus` 时，不会因为当前工作目录变化导致配置或模板找不到。
- 可通过环境变量 `ARGUS_PROJECT_ROOT` 覆盖项目根目录。

顶层 `config/` 目录只放配置数据，不放 Python 模块，避免和 `argus_py.config` 混淆。

## 项目上下文

后续维护前先阅读：

```text
docs/project-info/PROJECT_CONTEXT.md
```

该文档记录了当前阶段、近期改动、已知问题、待办事项和重点文件索引。

## 技术栈

| 组件 | 选型 |
|------|------|
| Python | 3.11+ |
| LLM | OpenAI Chat Completions 兼容接口 |
| 默认模型 | 百炼 Qwen3.5-Plus |
| 浏览器自动化 | Playwright Python |
| 报告 | Jinja2 HTML + JSON |
| 项目存储 | SQLite（`outputs/data/argus.db`） |
| 任务存储 | SQLite（`outputs/data/argus.db`）+ 文件系统产物 |
| 可观测性 | SQLite 时间线事件 + JSONL LLM Trace + WebSocket |
| Java 子模块 | Java 17 + Maven（第三阶段） |

## 注意事项

- 不要提交 `config/llm.env`。
- 不要在日志、文档或提交信息中输出 API Key。
- `argus browser check` 是浏览器封装调试入口，完整测试执行使用 `argus run`。
- 当前 LLM 检查命令只验证连接，不用于自由 Prompt 调试。
- LLM 调试页和调试包会记录 Prompt、输入 Payload 和原始响应；虽然敏感字段会按 key 脱敏，企业内部使用时仍应按调试资料管理，不要外发包含业务数据的调试包。
- 工作区可能存在大量未提交变更，修改前先查看 `git status --short`。
