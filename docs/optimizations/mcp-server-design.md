# Argus MCP Server 设计方案（AI 调用接口）

> 状态：设计稿（未实施）。本文描述为 AI 客户端（Claude、Cursor、IDE Agent 等）暴露
> Model Context Protocol（MCP）能力的方案。实施前需按 `docs/architecture.md` 第 11 节
> 确认是否需要补充 ADR；本文遵守现有架构基线，不解除任何硬约束。

## 1. 背景与目标

Argus 目前对外只有两类入口：Vue 控制台使用的 REST/WebSocket API，以及本地 CLI。两者都面向
人类操作。当用户希望让 AI 编排测试——"帮我跑一轮回归并总结新增问题"、"诊断任务为什么失败"，
AI 只能通过人肉转述或自行调用裸 REST，缺少标准化、可发现、带 schema 的工具协议。

MCP 是当前 AI 客户端普遍支持的开放协议，提供 Tools（可调用动作）、Resources（可读取数据）、
Prompts（提示模板）三类原语。为 Argus 增加 MCP 适配层后，AI 可以在权限受控的前提下直接
查询与操作 Argus 的领域能力。

### 成功标准

- AI 客户端可通过标准 MCP 发现并调用 Argus 能力，无需阅读 REST 文档。
- MCP 层是薄适配层：只做协议转换，复用既有应用服务与组合根，不出现第二套业务流程。
- 默认只读；写操作默认关闭，显式启用后每次调用有审计记录。
- 不破坏单进程/单副本约束：不引入第二个直连 SQLite 的业务进程。
- 工具契约稳定且向后兼容（只增不删不改语义），错误码复用现有稳定错误码体系。

## 2. 定位与架构边界

### 2.1 分层位置

MCP server 是**新的外层接口适配层**，与 `argus_py/api/`（FastAPI route）、`argus_py/cli/`
同级：

```text
MCP 客户端（AI）
      │  Streamable HTTP / stdio
      ▼
argus_py/mcp/            ← 新增：协议转换、工具注册、鉴权映射（薄层）
      ▼
TaskApplicationService / RegressionService / ProjectService / …   ← 既有应用编排层
      ▼
RuntimeContainer（唯一组合根）→ 存储 / 队列 / EventBus / Runner
```

硬约束继承自架构基线：

- `argus_py/mcp/` 不得创建共享存储、队列、HTTP 客户端或线程池；一切依赖来自
  `create_container()` 返回的 `RuntimeContainer`。
- 工具实现不得绕过 `TaskLifecycleService` 直接改任务状态，不得写 SQL、遍历文件。
- 任务状态变更仍只能走生命周期边界；MCP 只是触发入口之一。

### 2.2 部署形态：为什么不能是"独立 stdio 进程直连数据库"

架构现状：Python 队列、EventBus、容器均在进程内；lifespan 启动时对 outputs 目录获取跨进程
独占 OS 文件锁（O-02 fail-closed）。由此推导：

| 形态 | 可行性 | 结论 |
|------|--------|------|
| A. Streamable HTTP 挂载进 FastAPI 同一进程 | 与 `argus serve` 共享容器、队列、EventBus 和单实例锁 | **推荐，首期实现** |
| B. 独立 stdio 进程，但作为纯 HTTP 代理转发到运行中的 Argus | 不触碰 DB/outputs，无双写风险 | 允许，作为 IDE 本地接入的便捷形态（Phase 3） |
| C. 独立 stdio 进程直连 SQLite/outputs | 被 SingleInstanceLock 拒启（fail-closed），若绕过锁则任务双发、事件丢失 | **禁止** |

- 形态 A 下 MCP endpoint 挂在 `/argus/mcp`，由现有 Uvicorn 进程托管；`argus serve`
  关闭即 MCP 关闭，生命周期一致。
- 形态 B 的 stdio 进程是无状态转发器（等价于一个 CLI 客户端），不构成"独立部署服务"，
  不需要 ADR；它复用形态 A 暴露的同一 HTTP 契约。

### 2.3 协议实现选型

引入新依赖须给出理由（架构基线第 3 节）。候选：

1. **官方 `mcp` Python SDK（推荐）**：MCP 含 JSON-RPC 批处理、初始化握手、会话管理、
   SSE 流式传输等细节，自实现易漂移且维护成本高。SDK 只落在 `argus_py/mcp/adapter` 一层，
   不向应用层渗透。版本 pin 进 `pyproject.toml` + `uv.lock`（经 `uv sync --extra browser`
   安装）。
2. 自研最小 JSON-RPC 子集：仅实现 initialize/tools/list/tools/call。省一个依赖，但
   会话、分页、进度通知等后续都要自己补，长期成本更高。列为备选，仅在依赖政策不允许时采用。

## 3. 能力面设计

### 3.1 Tools（动作）

命名前缀 `argus_`，避免与其他 MCP server 冲突。每个工具对应一个既有应用服务的公开方法，
禁止在工具内实现业务逻辑。输入输出均为 Pydantic 模型生成的 JSON Schema。

**查询类（默认可用）：**

| Tool | 复用服务 | 说明 |
|------|----------|------|
| `argus_list_projects` | `ProjectService` | 项目列表（id、名称、目标 URL 摘要） |
| `argus_get_project` | `ProjectService` | 单项目详情 |
| `argus_list_tasks` | `TaskReadService` | 按 project/status/type 过滤，稳定分页 |
| `argus_get_task` | `TaskReadService` | 任务状态、参数视图、终态与报告路径 |
| `argus_get_task_logs` | `TaskReadService` / log 读路径 | 步骤日志（沿用脱敏后的响应模型） |
| `argus_get_task_findings` | findings 读路径 | 问题列表（severity/type/fingerprint） |
| `argus_get_report_json` | 报告读路径 | 已生成的结构化报告（同 `/report.json`） |
| `argus_list_analysis_runs` / `argus_get_analysis_run` | 白盒分析 run 读路径 | 分析状态、findings、diagnostics |
| `argus_list_regression_runs` / `argus_get_regression_summary` | `RegressionService` | 批次状态、门禁结果、差异摘要 |
| `argus_get_correlation_summary` | `CorrelationService` | 关联运行汇总 |
| `argus_query_task_timeline` | `TaskTimelineService` | 持久化时间线（重启后仍可查的事实） |
| `argus_search_llm_traces` | `TraceReadService` | LLM 调用轨迹检索（用于失败诊断） |
| `argus_get_stats` | dashboard stats 读路径 | 任务统计概览 |

**动作类（`ARGUS_MCP_WRITE_ENABLED=1` 才注册，默认不存在）：**

| Tool | 复用服务 | 说明 |
|------|----------|------|
| `argus_create_task` | `TaskApplicationService.create_task` | 创建任务，返回 task_id，不入队 |
| `argus_start_task` | lifecycle 启动边界 | 入队执行，立即返回（异步语义） |
| `argus_cancel_task` | `TaskLifecycleService` | 幂等取消 |
| `argus_restart_task` | lifecycle 重启边界 | 重跑既有任务 |
| `argus_create_regression_run` | `RegressionService` | 发起回归批次，返回 run_id |

动作类统一为**提交后轮询**语义：长操作只返回标识，不阻塞 MCP 请求直到完成；AI 通过查询类
工具跟踪进度。这同时避免长时间占用 Web 框架 worker 与触发 MCP 客户端超时。

**明确不暴露的能力：**

- 模型配置的增删改与连接测试（含密钥管理面，AI 无需也不应触碰）；
- WebSocket 订阅（MCP 无对应原语；实时性以时间线/状态轮询替代）;
- debug bundle 下载（含敏感调试信息，如需开放另做评审）;
- 项目删除、回归用例删除等不可逆删除类操作。

### 3.2 Resources（只读数据）

URI 模板（只增不改）：

```text
argus://projects                          → 项目列表
argus://projects/{project_id}             → 项目详情
argus://tasks/{task_id}                   → 任务详情
argus://tasks/{task_id}/report.json       → 结构化报告
argus://regression-runs/{run_id}/summary  → 回归批次汇总
```

Resources 是查询类工具的另一种发现形式，底层走同一批读服务；两者不得各自实现解析逻辑。

### 3.3 Prompts（模板)

- `diagnose-task-failure(task_id)`：组装任务终态 + 失败步骤日志 + 相关 LLM trace 摘要，
  引导 AI 输出根因假设与修复建议。
- `summarize-regression-diff(run_id)`：基于批次差异生成发布门禁结论摘要。
- `explain-analysis-findings(analysis_id)`：解读白盒 findings 与 diagnostics。

Prompts 由服务端拼装上下文（复用读服务），AI 客户端填充对话角色。

## 4. 契约设计

### 4.1 字段命名

- MCP 工具的入参/出参使用 **snake_case**（JSON Schema/MCP 生态惯例），是与 REST
  camelCase 契约相互独立的 wire contract。
- 两端从同一 Pydantic 领域模型分别序列化（REST 用 alias camelCase，MCP 用默认
  snake_case），字段逻辑单一事实来源，禁止手工复制映射代码。
- 新增工具/字段 = 兼容变更；改名、删除、收窄类型需要版本化迁移窗口并在本文记录。

### 4.2 错误映射

只在 MCP adapter 边界把应用层异常转换为 MCP 工具错误（`isError=true` + 结构化内容），
保留稳定错误码，不吞根因：

| 应用层情形 | MCP 返回 |
|-----------|----------|
| 校验失败（Pydantic/参数） | `code=VALIDATION_ERROR`，details 携带字段级错误 |
| 资源不存在 | `code=TASK_NOT_FOUND` / `PROJECT_NOT_FOUND` / … |
| 写开关未启用 | `code=MCP_WRITE_DISABLED`，message 说明开启方式 |
| 队列满 | `code=TASK_QUEUE_FULL`，附 `retry_after_seconds` 提示 AI 稍后重试 |
| 未认证 | JSON-RPC error（协议层 401 语义），不进入工具结果 |

### 4.3 版本与能力协商

- `serverInfo.version` 使用 `PROJECT_VERSION`；`instructions` 字段简要说明 Argus 能力
  与安全约束（帮助 AI 正确使用）。
- 工具列表通过 MCP 内建分页返回；首次发布后工具集合按"只增"演进。

## 5. 安全与权限

- **鉴权**：HTTP 形态复用 `ARGUS_API_TOKEN` 中间件机制；启用 MCP 时必须把 `/argus/mcp`
  加入受保护前缀（非回环监听强 Token 规则继续生效）。可选独立 `ARGUS_MCP_TOKEN` 以便
  单独撤销 AI 侧凭证；stdio 代理形态下 token 只存在于本地配置（`.gitignore` 已覆盖
  `.mcp.json`），不得写入仓库或日志。
- **默认只读**：查询类工具始终可用；动作类工具必须同时满足 (1) 显式配置开启
  (2) Token 鉴权已启用。两者缺一不可，防止匿名 AI 触发真实测试执行。
- **审计**：每次 tools/call 经 `AuditService` 记录 tool 名、参数摘要、来源会话、耗时与
  结果状态；参数中的密钥类字段沿用现有 redact 工具脱敏后再落日志。
- **注入防护**：MCP 输入全部经 Pydantic 校验；涉及路径的输入（如有）必须走现有 real-path/
  allowed-source-roots 校验器；不新增 shell 执行或任意 URL 抓取入口。
- **最小数据**：列表类工具返回摘要而非全量实体；截图等二进制资源不进 MCP 结果，
  返回经认证的引用 URI 即可。

## 6. 并发、超时与单实例

- MCP 与 API 同进程，不改变 `scheduler.concurrency`、LLM semaphore 等并发上限；
  不因 MCP 引入新的并行通道。
- 工具内的阻塞 IO 必须经统一 IO executor / `run_in_thread`，不阻塞事件循环（同 route 要求）。
- 每个 tool call 定义超时上限；动作类天然异步（提交即返回），查询类设置短超时快速失败，
  错误码提示重试。
- stdio 代理形态是普通 HTTP 客户端，自身无状态；断线重连由 MCP 客户端负责，Argus 侧
  无会话事实需要恢复。

## 7. 可观测性

- 模块 logger 遵守 `docs/logging.md`：结构化字段（tool、session、task_id、duration_ms、
  outcome），request/task context 传播复用现有工具。
- `/metrics` 增加 mcp 调用计数（可选，Phase 2）；健康检查不探测 MCP，MCP 故障不影响
  `/health` `/ready` 判定。
- 审计事件进入现有 audit 通道，便于回溯 AI 触发的动作。

## 8. 配置项

新增到 `ServerSettings`（env + config/server.yaml），业务模块不散落读环境变量：

| 配置 | 默认 | 说明 |
|------|------|------|
| `mcp.enabled` (`ARGUS_MCP_ENABLED`) | `false` | 总开关；关闭时不注册路由，零开销 |
| `mcp.write_enabled` (`ARGUS_MCP_WRITE_ENABLED`) | `false` | 动作类工具注册开关 |
| `mcp.token` (`ARGUS_MCP_TOKEN`) | 空 | 独立凭证；空则回落 `ARGUS_API_TOKEN` |
| `mcp.path` (`ARGUS_MCP_PATH`) | `/argus/mcp` | HTTP 挂载路径 |
| `mcp.tool_timeout_seconds` | 30 | 查询类工具超时 |

无数据库迁移需求（不新增表）；`.env.example` 同步补充示例与注释。

## 9. 测试与验证门禁

- **单元**：每个 tool handler 直调应用服务（fake storage），覆盖成功、校验失败、不存在、
  写开关关闭四类路径；断言未绕过 lifecycle（尝试改状态的路径不存在即可，由分层保证）。
- **集成**：httpx ASGI 客户端对挂载后的 app 跑完整 MCP 会话：initialize → tools/list →
  resources/list → tools/call；覆盖未认证 401、`ARGUS_MCP_WRITE_ENABLED=false` 时动作类
  工具不可见。
- **契约**：tools/list 输出的 schema 快照测试；意外漂移（改名/删除）直接失败，防止破坏
  已接入的 AI 客户端。
- **安全**：脱敏断言（trace/log 类工具输出不含密钥字段）；审计记录存在性断言。
- 门禁命令与现有规则一致：`uv run ruff check argus_py tests`、`uv run mypy argus_py`、
  `uv run pytest tests/unit tests/integration -q --tb=short`。

## 10. 实施计划

- **Phase 1 — 只读接入**：`argus_py/mcp/` 包骨架 + SDK 依赖 + 查询类工具 + Resources +
  鉴权集成 + 契约快照测试。默认 `mcp.enabled=false` 合入，风险最低。
- **Phase 2 — 受控写操作**：动作类工具 + 双开关 + 审计 + Prompts + metrics。
- **Phase 3 — stdio 代理（可选）**：`argus mcp-proxy` 子命令或独立薄脚本，转发 HTTP；
  供不支持远程 MCP 的本地 IDE 使用。不引入任何存储依赖。

每阶段独立合入、独立回滚（关掉对应配置开关即可），互为前置的只有包骨架。

## 11. 兼容 / 迁移 / 回滚

- **兼容**：不改动任何现有 REST/WS 契约与前端生成物；`codegen:check` 无差异预期。
  OpenAPI schema 不包含 MCP 路由（MCP 不是 OpenAPI 资源），如实现上误入需排除。
- **迁移**：无数据迁移；仅新增配置项，缺省关闭。
- **回滚**：设置 `ARGUS_MCP_ENABLED=false` 重启即完全关闭；移除依赖只影响
  `argus_py/mcp/` 包本身，无外部消费方。
- **风险**：SDK 版本升级可能改变协议行为 → 锁定 minor 版本并由契约快照测试兜底；
  AI 高频轮询造成读放大 → 列表工具强制分页上限，必要时复用限流中间件。

## 12. 开放问题（实施前确认）

1. 是否需要按项目粒度限制单个 MCP 会话可见的数据范围（多租户隔离目前不存在，MCP 沿用
   全局可见性与 REST 一致）。
2. `argus_search_llm_traces` 返回体较大，是否需要字段裁剪白名单。
3. stdio 代理是否值得随 Phase 3 提供，还是直接引导用户使用客户端内置的远程 MCP 支持
   （多数现代客户端已支持 streamable HTTP）。
