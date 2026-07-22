# Argus — AI 驱动 Web 测试平台

> 每一个 Bug，无处遁形。

别再写测试脚本了。开始描述你想要测试的行为。

Argus 是一个开源的、AI 驱动的 Web 测试平台。你只需要用自然语言描述你想检验的功能，剩下的交给 Argus：一个 LLM 负责规划浏览器操作，Playwright 负责执行，另一个 LLM 负责评估目标是否达成——每一步都有截图、DOM 快照和结构化报告。遇到失败时，Argus 会自动恢复重试，而不是直接放弃。

```bash
argus run --goal "提交联系表单，并验证成功提示" \
          --url "https://example.com/contact"
```

**为想要 AI 自动化测试却又不想维护脚本的团队而生。**

[English Documentation](README.md)

---

## 概述

Argus 在人类意图和自动化测试之间架起了一座桥梁。告别脆弱的 Selenium 脚本和复杂的 Playwright 代码，用一句话描述你想测试的内容：

```bash
argus run --goal "测试登录表单——检查必填字段和错误提示" --url "https://example.com/login"
```

系统自动完成规划、执行、失败恢复、证据收集（截图、DOM 快照）和报告生成。

### 适用场景

| 场景 | 说明 |
|------|------|
| **探索性测试** | 快速验证页面渲染、链接可用、表单提交 |
| **回归冒烟测试** | 复用保存的登录态，跨部署环境检查需要登录的页面 |
| **表单与登录流程验证** | 测试验证规则、错误状态和提交流程 |
| **发布前健康检查** | 在发布前自动化批量 URL 检查 |
| **Demo / 原型 QA** | 在 UI 频繁变动的早期产品上获得测试覆盖 |

---

## 功能特性

- **自然语言测试执行** — 描述测试目标，Argus 自动规划执行步骤
- **LLM 驱动的 Planner 和 Evaluator** — 双 LLM 架构：一个规划操作，一个评判是否达成目标，均支持项目和任务级别的业务规则扩展
- **自我修复执行** — 失败不会终止任务，Argus 记录失败、重新观察页面并通过失败感知重规划来恢复（默认 2 次重试）
- **Playwright 浏览器自动化** — 支持 Chromium、Firefox、WebKit，提供 goto、click、type、select、wait、截图及智能选择器推荐的 DOM 快照
- **浏览器登录态管理** — 一次保存登录状态（Cookie、localStorage），跨任务复用
- **结构化报告** — HTML 报告（可折叠步骤、可点击放大的截图）和 JSON 报告（机器可读）
- **任务可观测性** — 基于 SQLite 的任务执行时间线、实时 WebSocket 推送、LLM 调用全链路追踪（含完整 prompt/response/error）和 ZIP 调试包
- **模型配置管理** — 多 LLM 提供商配置存储在 SQLite 中，API Key 加密存储（Fernet），可按任务分配
- **Prompt 业务扩展** — 项目和任务级别附加自定义规则至 Planner/Evaluator 的 prompt，无需修改内置模板
- **敏感数据脱敏** — 递归屏蔽日志和追踪中的 api_key、password、token、authorization 等敏感字段
- **Web 管理后台** — Vue 3 + Element Plus SPA，管理项目、任务、模型，查看带时间线和 LLM 调试面板的报告
- **REST API + WebSocket** — 完整 RESTful API，OpenAPI 文档，实时任务事件推送
- **Docker 部署** — 容器化部署，内置 SSRF 防护、CORS/WebSocket 来源校验、限流、可选 API Token 认证、自动数据库备份和 Schema 迁移

---

## 快速开始

### 前置条件

- Python 3.11+
- Playwright 浏览器环境
- 兼容 OpenAI Chat Completions 的 LLM API

### 安装

```bash
pip install -e ".[dev]"
argus --version
```

安装 Playwright Chromium：

```bash
playwright install chromium
```

### 本地开发一键启动

项目提供零依赖的 Node.js 开发进程管理器，可在 Windows、macOS 和 Linux 上同时
启动 Python API、Vue 前端和 Java 分析器，并在当前终端统一显示日志。

先使用 uv 创建锁定的 Python 环境并安装前端依赖：

```bash
uv sync --frozen --extra browser --dev
pnpm --dir frontend install --frozen-lockfile
```

检查 uv、Python、pnpm、Maven/JDK 及开发端口，但不启动服务：

```bash
node scripts/dev.mjs --check
```

一键启动全部服务：

```bash
node scripts/dev.mjs
```

启动完成后访问前端 `http://127.0.0.1:5173`。Python 和前端支持热更新；Java
源码修改后需要按 `Ctrl+C` 停止，再重新启动整组服务。任一服务异常退出时，管理器
也会停止其余服务，避免残留半套开发环境。

每次启动的汇总日志和各服务日志保存在
`outputs/logs/dev/<启动时间>/`。日志可能包含敏感运行信息，请勿未经检查直接外传。

### 配置 LLM

```bash
argus config llm
```

按照提示配置 API Key、接口地址和模型名称，配置会保存到数据库（加密存储）。

验证连通性：

```bash
argus llm check
```

### 运行你的第一个测试

```bash
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

---

## CLI 参考

| 命令 | 说明 |
|------|------|
| `argus serve` | 启动 FastAPI Web 服务 |
| `argus run --goal <text> --url <url>` | 执行黑盒测试任务 |
| `argus run --create-only` | 仅创建任务快照，不执行 |
| `argus browser check --url <url>` | 调试浏览器能力 |
| `argus auth save --url <url>` | 保存浏览器登录态 |
| `argus auth list` | 列出已保存的浏览器登录态 |
| `argus llm check` | 验证 LLM API 连通性 |
| `argus config llm` | 交互式 LLM 配置 |
| `argus config llm --advanced` | 配置高级参数（max tokens、temperature、retries） |

### `argus run` 选项

| 选项 | 说明 |
|------|------|
| `--goal` | 自然语言描述测试目标 |
| `--url` | 目标 URL |
| `--headed` | 执行时显示浏览器窗口 |
| `--auth-state <name>` | 复用已保存的浏览器登录态 |
| `--no-screenshot` | 禁用步骤截图 |
| `--create-only` | 创建任务快照但不执行 |
| `--project <id>` | 将任务关联到项目 |
| `--max-steps <n>` | 覆盖最大规划步数 |
| `--timeout <s>` | 覆盖执行超时 |
| `--planner-extension <file>` | Planner prompt 的自定义规则文件 |
| `--evaluator-extension <file>` | Evaluator prompt 的自定义规则文件 |

---

## Web 管理后台 & API

启动 Web 服务：

```bash
argus serve
# 访问 http://localhost:8000
```

Web 管理后台（Vue 3 SPA）提供：

- **仪表盘** — 项目和任务概览
- **项目管理** — 增删改查，Markdown 编辑器编辑 prompt 扩展，实时预览系统 prompt
- **任务管理** — 创建、启动、停止任务；查看报告、执行时间线和 LLM 调试追踪
- **模型管理** — 管理 LLM 提供商配置，测试连通性

### 核心 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET/POST | `/argus/api/projects` | 列出 / 创建项目 |
| GET/POST | `/argus/api/tasks` | 列出 / 创建任务 |
| POST | `/argus/api/tasks/{id}/start` | 开始执行任务 |
| POST | `/argus/api/tasks/{id}/stop` | 停止运行中的任务 |
| GET | `/argus/api/tasks/{id}/report` | 获取任务报告（HTML 或 JSON） |
| GET | `/argus/api/tasks/{id}/events` | 获取执行时间线 |
| GET | `/argus/api/tasks/{id}/llm-traces` | 获取 LLM 调用追踪 |
| GET | `/argus/api/tasks/{id}/debug-bundle` | 下载调试包（ZIP） |
| GET/POST | `/argus/api/config/models` | 管理模型配置 |
| WS | `/argus/api/ws/tasks/{id}` | 实时任务事件推送 |
| — | `/docs` | OpenAPI / Swagger UI |

---

## 架构

```
┌─────────────────────────────────────────────────┐
│                   CLI (argus)                    │
│  run │ serve │ browser │ auth │ llm │ config     │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              FastAPI Web Server                  │
│  REST API │ WebSocket │ Vue 3 Console (SPA)      │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              Black-box Agent                     │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐       │
│  │ Planner │─►│ Executor │─►│ Evaluator │       │
│  │  (LLM)  │  │Playwright│  │  (LLM)    │       │
│  └─────────┘  └──────────┘  └───────────┘       │
│         │           │              │             │
│         ▼           ▼              ▼             │
│   Step Logs    Screenshots    Issue Records      │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              Infrastructure                      │
│  SQLite │ File System │ Event Bus │ Task Queue   │
└─────────────────────────────────────────────────┘
```

**执行流程：**

1. **Planner** (LLM) 接收目标 + 页面快照，输出下一个浏览器操作
2. **Executor** 通过 Playwright 执行操作，截取屏幕截图和 DOM 快照
3. **Evaluator** (LLM) 判定目标是否达成
4. 未达成则回到 Planner，携带更新后的上下文继续循环
5. 失败时，恢复逻辑重新观察页面并重规划（最多 2 次重试）
6. 目标达成或超时/达最大步数后，生成 HTML + JSON 报告

---

## Prompt 扩展系统

Argus 将内置 Prompt 与用户扩展分离：

- **内置模板** (`argus_py/llm/prompts/`) — 随包发布的 Planner 和 Evaluator Prompt，**不可覆盖**
- **业务扩展** — 按项目或任务通过 `parameters.prompt_extensions.{planner,evaluator}` 附加自定义规则

拼接顺序：`内置 Prompt → 项目扩展 → 任务扩展`

这样可以在不改动代码库的前提下，为每个应用定制测试行为。Web 管理后台提供带实时系统 Prompt 预览的 Markdown 编辑器。

---

## 技术栈

| 组件 | 选型 |
|------|------|
| Python | 3.11+ |
| LLM API | 兼容 OpenAI Chat Completions |
| 浏览器 | Playwright (Chromium) |
| Web 框架 | FastAPI + Uvicorn |
| 前端 | TypeScript + Vue 3 + Element Plus + Vite |
| 报告 | Jinja2 (HTML) + JSON |
| 数据库 | SQLite (WAL mode) |
| 可观测性 | SQLite 事件 + JSONL 追踪 + WebSocket |
| 部署 | Docker / Docker Compose |

---

## 项目结构

```
argus/
├── argus_py/
│   ├── cli/           # CLI 入口和交互式提示
│   ├── api/           # FastAPI 应用、路由、Schema、中间件、静态文件托管
│   ├── core/          # 常量、路径、枚举、异常、ID 生成
│   ├── config/        # 配置加载、模型配置服务、SQLite 存储
│   ├── llm/           # LLM 客户端、提供商适配器、Prompt、解析、重试
│   ├── observability/ # 审计日志、脱敏、LLM 追踪
│   ├── task/          # 任务模型、状态机、SQLite 存储、时间线、生命周期
│   ├── blackbox/      # Planner、Executor、Evaluator、恢复逻辑
│   ├── browser/       # Playwright 生命周期、操作、选择器、快照
│   ├── report/        # 报告模型、HTML/JSON 导出
│   ├── project/       # 项目模型、SQLite 存储、CRUD
│   ├── infra/         # SQLite 基础设施、迁移、任务队列、事件总线
│   ├── execution/     # 任务运行器外观层
│   ├── runtime/       # 依赖注入容器
│   └── whitebox/      # Java 白盒分析桩（计划中）
├── frontend/          # TypeScript + Vite + Vue 3 SPA 源码
├── config/            # 配置文件 (logging.yaml, server.yaml)
├── docs/              # 文档
├── tests/             # 单元测试、契约测试、集成测试
├── examples/          # 示例任务 JSON 文件
├── scripts/           # 实用脚本（备份、清理）
├── outputs/           # 运行时产物（报告、截图、追踪）— gitignored
└── java_analyzer/     # Java 分析器子模块桩（计划中）
```

---

## 部署

Argus 支持基于 Docker 的私有网络部署。详见[部署指南](docs/deployment.md)：

- Docker Compose 搭建
- SSRF 防护和 CORS 配置
- API Token 认证
- 自动数据库备份
- Schema 迁移
- 安全加固

---

## License

MIT
