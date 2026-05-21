# Argus — AI Native 测试平台

> 每个 Bug 都无处藏身。

Argus 是一个面向 Web 应用质量保障场景的 AI Native 测试平台。用自然语言描述测试目标，Argus 会替你完成一切：大模型规划浏览器动作，Playwright 执行操作，最终输出结构化测试报告——全流程自动化。

[English](README.md)

---

## 概述

Argus 弥合了人类意图与自动化测试之间的鸿沟。无需编写脆弱的 Selenium 脚本或复杂的 Playwright 代码，只需用自然语言描述你想要测试的内容：

```bash
argus run --goal "测试登录表单——检查必填校验和错误提示" --url "https://example.com/login"
```

系统会处理规划、执行、失败恢复、证据收集（截图、DOM 快照）和报告生成。专为希望使用 AI 驱动测试自动化但又不想维护大量脚本的团队而设计。

### 使用场景

| 场景 | 说明 |
|------|------|
| **探索性测试** | 快速验证页面是否正确渲染、链接是否可用、表单能否提交 |
| **回归冒烟测试** | 复用已保存的登录态，在每次部署后检查需登录的页面 |
| **表单和登录流程验证** | 测试验证规则、错误状态和提交流程 |
| **发布前健康检查** | 在发布前自动化执行一组 URL 检查 |
| **Demo / 原型 QA** | 为 UI 频繁变更的早期产品提供测试覆盖 |

---

## 功能特性

- **自然语言测试执行** — 描述测试目标，Argus 自动规划执行步骤
- **LLM 驱动的规划器与评估器** — 两个专用 Prompt：一个规划浏览器动作，一个判断目标是否达成。支持按项目或任务追加业务规则扩展
- **自愈执行** — 动作失败不会中止任务。系统记录失败、重新观察页面，并基于失败历史重新规划（默认 2 次恢复尝试）
- **Playwright 浏览器自动化** — 支持 Chromium、Firefox、WebKit。提供 goto、click、type、select、wait、截图和 DOM 快照，附带智能选择器推荐
- **浏览器登录态管理** — 通过 `argus auth save / list` 和 `--auth-state` 一次保存登录态，跨任务复用
- **结构化报告** — 每项任务输出 HTML 报告（可折叠步骤、截图点击放大）和 JSON 报告（机器可读）
- **任务可观测性** — 任务执行时间线持久化到 SQLite、实时 WebSocket 事件推送、LLM 调用追踪（完整 Prompt/响应/错误）和 ZIP 调试包下载
- **模型配置管理** — 多种 LLM 提供商配置存储在 SQLite 中，API Key 加密存储（Fernet），可按任务分配
- **Prompt 业务扩展** — 在项目或任务级别为 Planner/Evaluator 追加自定义规则，无需修改内置模板
- **敏感数据脱敏** — 在日志、追踪和调试包中递归屏蔽 api_key、password、token、authorization 等字段
- **Web 控制台** — Vue 3 + Element Plus 单页应用，支持项目管理、任务管理、模型配置，以及报告、执行时间线和 LLM 调试页签
- **REST API + WebSocket** — 完整的 RESTful API 和 OpenAPI 文档，通过 WebSocket 实时推送任务事件
- **Docker 部署** — 容器化，支持 SSRF 防护、CORS/WebSocket Origin 校验、限流、可选 API Token 认证、自动数据库备份和 Schema 迁移

---

## 快速开始

### 环境要求

- Python 3.11+
- Playwright 浏览器运行环境
- 兼容 OpenAI Chat Completions 的大模型 API

### 安装

```bash
pip install -e ".[dev]"
argus --version
```

安装 Playwright Chromium：

```bash
playwright install chromium
```

### 配置大模型

```bash
argus config llm
```

该命令会交互式引导你输入 API Key、接口地址和模型名称。配置保存在 `config/llm.env`（已排除出版本控制）。

验证连接：

```bash
argus llm check
```

### 运行你的第一个测试

```bash
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

---

## CLI 命令参考

| 命令 | 说明 |
|------|------|
| `argus serve` | 启动 FastAPI Web 服务器 |
| `argus run --goal <text> --url <url>` | 执行黑盒测试任务 |
| `argus run --create-only` | 仅创建任务快照，不执行 |
| `argus browser check --url <url>` | 调试浏览器能力 |
| `argus auth save --url <url>` | 保存浏览器登录态 |
| `argus auth list` | 列出已保存的浏览器登录态 |
| `argus llm check` | 验证大模型 API 连通性 |
| `argus config llm` | 交互式配置大模型 |
| `argus config llm --advanced` | 配置高级参数（最大 Token 数、温度、重试次数） |

### `argus run` 参数

| 参数 | 说明 |
|------|------|
| `--goal` | 自然语言描述的测试目标 |
| `--url` | 目标 URL |
| `--headed` | 执行时显示浏览器窗口 |
| `--auth-state <name>` | 复用已保存的浏览器登录态 |
| `--no-screenshot` | 关闭步骤截图 |
| `--create-only` | 仅创建任务快照，不执行 |
| `--project <id>` | 关联项目 |
| `--max-steps <n>` | 覆盖最大规划步数 |
| `--timeout <s>` | 覆盖执行超时 |
| `--planner-extension <file>` | Planner Prompt 的自定义规则文件 |
| `--evaluator-extension <file>` | Evaluator Prompt 的自定义规则文件 |

---

## Web 控制台 & API

启动 Web 服务器：

```bash
argus serve
# 访问 http://localhost:8000
```

Web 控制台（Vue 3 SPA）提供：

- **仪表盘** — 项目和任务概览
- **项目管理** — 增删改查，Prompt 扩展编辑器（带实时完整 Prompt 预览）
- **任务管理** — 创建、启动、停止；查看报告、执行时间线和 LLM 调试追踪
- **模型配置** — 管理 LLM 提供商配置，测试连通性

### 主要 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET/POST | `/api/v1/projects` | 列出/创建项目 |
| GET/POST | `/api/v1/tasks` | 列出/创建任务 |
| POST | `/api/v1/tasks/{id}/start` | 启动任务执行 |
| POST | `/api/v1/tasks/{id}/stop` | 停止运行中的任务 |
| GET | `/api/v1/tasks/{id}/report` | 获取任务报告（HTML 或 JSON） |
| GET | `/api/v1/tasks/{id}/events` | 获取执行时间线 |
| GET | `/api/v1/tasks/{id}/llm-traces` | 获取 LLM 调用追踪 |
| GET | `/api/v1/tasks/{id}/debug-bundle` | 下载调试包（ZIP） |
| GET/POST | `/api/v1/config/models` | 管理模型配置 |
| WS | `/api/v1/ws/tasks/{id}` | 实时任务事件 |
| — | `/docs` | OpenAPI / Swagger 文档 |

---

## 架构

```
┌─────────────────────────────────────────────────┐
│                 CLI (argus)                      │
│  run │ serve │ browser │ auth │ llm │ config     │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              FastAPI Web Server                  │
│  REST API │ WebSocket │ Vue 3 Console (SPA)      │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              黑盒 Agent                          │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐       │
│  │ Planner │─►│ Executor │─►│ Evaluator │       │
│  │  (LLM)  │  │Playwright│  │  (LLM)    │       │
│  └─────────┘  └──────────┘  └───────────┘       │
│         │           │              │             │
│         ▼           ▼              ▼             │
│   步骤日志      截图        问题记录             │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              基础设施                             │
│  SQLite │ 文件系统 │ 事件总线 │ 任务队列          │
└─────────────────────────────────────────────────┘
```

**执行流程：**

1. **Planner（LLM）** 接收测试目标和页面快照，输出下一步浏览器动作
2. **Executor** 通过 Playwright 执行动作，采集截图和 DOM 快照
3. **Evaluator（LLM）** 评估目标是否达成
4. 若未达成，携带更新后的上下文重新进入规划循环
5. 执行失败时，恢复机制重新观察页面并重新规划（最多 2 次重试）
6. 完成后生成 HTML + JSON 报告

---

## Prompt 扩展系统

Argus 将内置 Prompt 与用户扩展分离：

- **内置模板**（`argus_py/llm/prompts/`）— Planner 和 Evaluator 的 Prompt 随包发布，**不可覆盖**
- **业务扩展** — 通过 `parameters.prompt_extensions.{planner,evaluator}` 为每个项目或任务追加自定义规则

拼接顺序：`内置 → 项目扩展 → 任务扩展`

这样可以在不改动代码库的前提下，针对不同应用定制测试行为。Web 控制台提供了 Markdown 编辑器和实时完整 Prompt 预览。

**任务级扩展**：

```bash
argus run --goal "..." --url "..." \
  --planner-extension ./my-rules/planner.md \
  --evaluator-extension ./my-rules/evaluator.md
```

---

## 技术栈

| 组件 | 选型 |
|------|------|
| Python | 3.11+ |
| LLM API | OpenAI Chat Completions 兼容接口 |
| 浏览器 | Playwright（Chromium） |
| Web 框架 | FastAPI + Uvicorn |
| 前端 | TypeScript + Vue 3 + Element Plus + Vite |
| 报告 | Jinja2（HTML）+ JSON |
| 数据库 | SQLite（WAL 模式） |
| 可观测性 | SQLite 事件 + JSONL 追踪 + WebSocket |
| 部署 | Docker / Docker Compose |

---

## 项目结构

```
argus/
├── argus_py/
│   ├── cli/           # CLI 入口与交互提示
│   ├── api/           # FastAPI 应用、路由、Schema、中间件、静态托管
│   ├── core/          # 常量、路径、枚举、异常、ID
│   ├── config/        # 配置加载、模型配置服务、SQLite 存储
│   ├── llm/           # LLM 调用、供应商适配、Prompt、解析、重试
│   ├── observability/ # 审计、脱敏、LLM 追踪
│   ├── task/          # 任务模型、状态机、SQLite 存储、时间线、生命周期
│   ├── blackbox/      # Planner、Executor、Evaluator、恢复
│   ├── browser/       # Playwright 生命周期、动作、选择器、快照
│   ├── report/        # 报告模型、HTML/JSON 导出
│   ├── project/       # 项目模型、SQLite 存储、CRUD
│   ├── infra/         # SQLite 基础设施、迁移、任务队列、事件总线
│   ├── execution/     # 任务执行器外观
│   ├── runtime/       # DI 容器
│   └── whitebox/      # Java 白盒分析占位（规划中）
├── frontend/          # TypeScript + Vite + Vue 3 SPA 源码
├── config/            # 配置文件（llm.env, logging.yaml, server.yaml）
├── docs/              # 文档
├── tests/             # 单元测试、契约测试和集成测试
├── examples/          # 示例任务 JSON
├── scripts/           # 工具脚本（备份、清理）
├── outputs/           # 运行产物（报告、截图、追踪）— gitignored
└── java_analyzer/     # Java 分析器子模块占位（规划中）
```

---

## 部署

Argus 支持基于 Docker 的私网部署。详见[部署指南](docs/deployment.md)，涵盖：

- Docker Compose 搭建
- SSRF 防护和 CORS 配置
- API Token 认证
- 自动数据库备份
- Schema 迁移
- 安全加固

---

## 许可

MIT
