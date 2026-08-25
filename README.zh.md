# Argus — AI 驱动 Web 测试平台

> 每一个 Bug，无处遁形。

别再写测试脚本了。开始描述你想要测试的行为。

Argus 是一个开源的、AI 驱动的 Web 测试平台。你只需要用自然语言描述你想检验的功能：黑盒测试由一个 LLM 规划浏览器操作、Playwright 负责执行、另一个 LLM 评估目标是否达成——每一步都有截图、DOM 快照和结构化报告。遇到失败时，Argus 会自动恢复重试，而不是直接放弃。

除浏览器之外，Argus 还支持对 Java 代码库进行**白盒分析**：基于 Spring Boot 和 JavaParser 的分析服务从源码中提取 REST 端点、调用图、执行流和功能聚类。黑盒执行期间捕获的 HTTP 请求证据会与这些端点进行关联——把"屏幕上发生了什么"和"代码里发生了什么"连接起来。

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

系统自动完成规划、执行、失败恢复、证据收集（截图、DOM 快照、HTTP 请求证据）和报告生成。

### 适用场景

| 场景 | 说明 |
|------|------|
| **探索性测试** | 快速验证页面渲染、链接可用、表单提交 |
| **回归冒烟测试** | 复用保存的登录态，跨部署环境检查需要登录的页面 |
| **表单与登录流程验证** | 测试验证规则、错误状态和提交流程 |
| **发布前健康检查** | 在发布前自动化批量 URL 检查 |
| **Demo / 原型 QA** | 在 UI 频繁变动的早期产品上获得测试覆盖 |
| **Java 代码库洞察** | 从 Java 仓库提取 REST 端点、调用图和执行流 |
| **黑白盒关联** | 把 UI 层的 HTTP 流量映射回服务端代码路径 |

---

## 功能特性

- **自然语言测试执行** — 描述测试目标，Argus 自动规划执行步骤
- **LLM 驱动的 Planner 和 Evaluator** — 双 LLM 架构：一个规划操作，一个评判是否达成目标，均支持项目和任务级别的业务规则扩展
- **自我修复执行** — 失败不会终止任务，Argus 记录失败、重新观察页面并通过失败感知重规划来恢复（默认 2 次重试）
- **Playwright 浏览器自动化** — 支持 Chromium、Firefox、WebKit，提供 goto、click、type、select、wait、截图及智能选择器推荐的 DOM 快照
- **白盒静态分析** — `argus analyze` 对 Git 仓库或本地目录做源码快照，交给 Java Analyzer 服务（Spring Boot + JavaParser + Maven classpath 解析）。分析范围：完整分析、增量变更、指定模块、端点抽取、调用图、执行流、功能聚类。结果包含 REST 端点、调用图、发现项、执行流和功能聚类，并生成 HTML/JSON 报告
- **黑白盒关联** — 黑盒执行期间捕获的 HTTP 请求与白盒端点匹配，把 UI 行为关联到服务端代码路径，关联运行全程可审计
- **浏览器登录态管理** — 一次保存登录状态（Cookie、localStorage），跨任务复用
- **结构化报告** — HTML 报告（可折叠步骤、可点击放大的截图）和 JSON 报告（机器可读），黑盒与白盒任务均支持
- **任务可观测性** — 基于 SQLite 的任务执行时间线、实时 WebSocket 推送、LLM 调用全链路追踪（含完整 prompt/response/error）和 ZIP 调试包
- **模型配置管理** — 多 LLM 提供商配置存储在 SQLite 中，API Key 加密存储（Fernet），可按任务分配
- **Prompt 业务扩展** — 项目和任务级别附加自定义规则至 Planner/Evaluator 的 prompt，无需修改内置模板
- **敏感数据脱敏** — 递归屏蔽日志和追踪中的 api_key、password、token、authorization 等敏感字段
- **Web 管理后台** — Vue 3 + Element Plus SPA，管理项目、任务、模型，查看黑盒/白盒报告、时间线、LLM 调试面板和关联摘要
- **REST API + WebSocket** — 完整 RESTful API，OpenAPI 文档，实时任务事件推送
- **Docker 部署** — 容器化部署，内置 SSRF 防护、CORS/WebSocket 来源校验、限流、可选 API Token 认证、自动数据库备份和 Schema 迁移

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 20+ 和 pnpm（仅前端开发需要）
- Playwright 浏览器环境
- 兼容 OpenAI Chat Completions 的 LLM API

### 安装

安装 Argus 及浏览器扩展依赖：

```bash
pip install -e ".[browser]"
```

安装 Playwright Chromium：

```bash
playwright install chromium
```

验证 CLI：

```bash
argus --version
```

> 仓库贡献者可以使用 [uv](https://docs.astral.sh/uv/) 管理环境，
> 见下文「本地开发一键启动」。

### 本地开发一键启动

项目提供零依赖的 Node.js 开发进程管理器，可在 Windows、macOS 和 Linux 上同时
启动 Python API、Vue 前端和 Java 分析器，并在当前终端统一显示日志。

准备一个已安装项目依赖的 Python 3.11+ 环境，并安装前端依赖：

```bash
uv sync --extra browser        # 推荐（需要 uv）；无 uv 时改用：pip install -e ".[browser]"
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
| `argus run --goal <text> --url <url>` | 执行黑盒测试任务 |
| `argus analyze --repo <url>` / `argus analyze --source-path <dir>` | 执行白盒分析任务 |
| `argus serve` | 启动 FastAPI Web 服务 |
| `argus run --create-only` | 仅创建任务快照，不执行 |
| `argus browser check --url <url>` | 调试浏览器能力 |
| `argus auth save --url <url>` | 保存浏览器登录态 |
| `argus auth list` | 列出已保存的浏览器登录态 |
| `argus llm check` | 验证 LLM API 连通性 |
| `argus config llm` | 交互式 LLM 配置 |
| `argus config llm --advanced` | 配置高级参数（max tokens、temperature、retries） |

全局选项：`-v` / `-vv` 分别提升日志级别到 INFO / DEBUG。

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

### `argus analyze` 选项

| 选项 | 说明 |
|------|------|
| `--repo <url>` | Git 仓库 URL（与 `--source-path` 二选一） |
| `--source-path <dir>` | 本地源码目录（与 `--repo` 二选一） |
| `--branch <name>` | 分析分支（仅配合 `--repo`） |
| `--scope <s>` | `all`（默认）、`changed`、`modules`、`endpoints`、`callgraph`、`flows`、`clusters` |
| `--project <id>` | 将任务关联到项目 |
| `--target-modules <m...>` | 目标 Maven 模块（`--scope modules` 时必填） |
| `--classpath-mode <mode>` | 类路径策略：`auto` / `cache-only` / `maven` / `source-only` |
| `--maven-executable`、`--maven-settings`、`--local-repository`、`--maven-offline`、`--maven-classpath-file`、`--prepare-reactor` | Maven classpath 解析相关参数 |

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
- **任务管理** — 创建、启动、停止任务；查看黑盒报告、白盒报告、执行时间线、LLM 调试追踪和黑白盒关联摘要
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
| GET | `/argus/api/tasks/{id}/analysis-runs` | 查询任务的白盒分析运行记录 |
| GET | `/argus/api/correlation-runs/{id}` | 获取关联运行详情（另有 `attempts`、`summary` 及证据端点） |
| GET/POST | `/argus/api/config/models` | 管理模型配置 |
| WS | `/argus/api/ws/tasks/{id}` | 实时任务事件推送 |
| — | `/docs` | OpenAPI / Swagger UI |

---

## 架构

```
┌───────────────────────────────────────────────────────┐
│                      CLI (argus)                      │
│ run │ analyze │ serve │ browser │ auth │ llm │ config │
└───────────┬───────────────────────────────────────────┘
            │
┌───────────▼───────────────────────────────────────────┐
│                  FastAPI Web Server                   │
│   REST API │ WebSocket │ Vue 3 Console (SPA)          │
└───────────┬───────────────────────────────────────────┘
            │
┌───────────▼───────────────────────────────────────────┐
│                      Task Runner                      │
│                                                       │
│ ┌─ Black-box Agent ──────┐    ┌─ White-box ─────────┐ │
│ │ Planner → Executor →   │    │ Source snapshot →   │ │
│ │ Evaluator (LLM loop)   │    │ HTTP JSON → Java    │ │
│ │ Playwright execution + │    │ Analyzer (Spring    │ │
│ │ HTTP evidence capture  │    │ Boot + JavaParser)  │ │
│ └───────────┬────────────┘    └──────────┬──────────┘ │
│             └────── Correlation ─────────┘            │
└───────────┬───────────────────────────────────────────┘
            │
┌───────────▼───────────────────────────────────────────┐
│                    Infrastructure                     │
│ SQLite │ File System │ Event Bus │ Task Queue         │
└───────────────────────────────────────────────────────┘
```

**黑盒执行流程：**

1. **Planner** (LLM) 接收目标 + 页面快照，输出下一个浏览器操作
2. **Executor** 通过 Playwright 执行操作，截取屏幕截图、DOM 快照和 HTTP 请求证据
3. **Evaluator** (LLM) 判定目标是否达成
4. 未达成则回到 Planner，携带更新后的上下文继续循环
5. 失败时，恢复逻辑重新观察页面并重规划（最多 2 次重试）
6. 目标达成或超时/达最大步数后，生成 HTML + JSON 报告

**白盒分析流程：**

1. Python 对源码做快照（Git clone 或本地复制）
2. 通过版本化 HTTP/JSON 契约发送给 Java Analyzer
3. JavaParser + Maven classpath 解析产出端点、调用图、发现项、执行流和聚类
4. 结果持久化并渲染为白盒 HTML/JSON 报告

**黑白盒关联：** 黑盒捕获的 HTTP 请求证据与抽取的端点匹配，生成可审计的关联运行记录，把 UI 行为链接到服务端代码。

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
| Python | 3.11+（使用 uv + `uv.lock` 管理） |
| LLM API | 兼容 OpenAI Chat Completions |
| 浏览器 | Playwright (Chromium) |
| Web 框架 | FastAPI + Uvicorn |
| 前端 | TypeScript + Vue 3 + Element Plus + Vite |
| 静态分析引擎 | Java 21 · Spring Boot · JavaParser |
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
│   ├── observability/ # 审计日志、LLM 追踪
│   ├── redaction/     # 敏感数据脱敏工具
│   ├── task/          # 任务模型、状态机、SQLite 存储、时间线、生命周期
│   ├── execution/     # 任务运行器外观层
│   ├── runtime/       # 依赖注入容器（组合根）
│   ├── blackbox/      # Planner、Executor、Evaluator、恢复逻辑
│   ├── browser/       # Playwright 生命周期、操作、选择器、快照
│   ├── whitebox/      # 白盒客户端、源码解析、Runner、投影
│   ├── analysis/      # 分析运行模型、分析范围、质量问题
│   ├── correlation/   # 黑白盒关联服务与证据模型
│   ├── report/        # 报告模型、HTML/JSON 导出
│   ├── project/       # 项目模型、SQLite 存储、CRUD
│   ├── infra/         # SQLite 基础设施、迁移、任务队列、事件总线
│   └── utils/         # 日志、文件 IO、JSON 工具
├── frontend/          # TypeScript + Vite + Vue 3 SPA 源码
├── java_analyzer/     # Spring Boot 分析服务（JavaParser + Maven classpath）
├── config/            # 配置文件 (logging.yaml, server.yaml)
├── docs/              # 文档（架构、手册、CLI、部署）
├── tests/             # 单元测试、契约测试、集成测试
├── examples/          # 示例任务 JSON 文件
├── scripts/           # 开发进程管理器 (dev.mjs)、备份、清理脚本
└── outputs/           # 运行时产物（报告、截图、追踪）— gitignored
```

---

## 部署

Argus 支持基于 Docker 的私有网络部署。核心服务使用单个容器；需要白盒分析时
追加 `--profile java` 启动 Java Analyzer：

```bash
docker compose up -d --build                      # 核心（黑盒 + 控制台）
docker compose --profile java up -d --build       # 核心 + Java Analyzer
```

详见[部署指南](docs/deployment.zh.md)：

- Docker Compose 搭建与内网覆盖文件
- SSRF 防护和 CORS 配置
- API Token 认证
- 自动数据库备份
- Schema 迁移
- 安全加固

---

## 文档

| 文档 | 内容 |
|------|------|
| [架构基线](docs/architecture.md) | 架构事实来源、分层边界与演进约束 |
| [用户手册](docs/guide.zh.md) | 配置、Web 控制台、Prompt 扩展、报告解读、故障排查 |
| [CLI 参考](docs/cli.zh.md) | 完整命令与选项说明 |
| [部署指南](docs/deployment.zh.md) | Docker 部署与运维 |
| [日志规范](docs/logging.md) | 日志与可观测性约定 |

---

## License

MIT
