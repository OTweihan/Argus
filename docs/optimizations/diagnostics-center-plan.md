# Argus 诊断中心建设方案

> **实施状态（2026-09-02）**
>
> - **MVP（已落地）**：服务状态、运行日志检索/详情/上下文、Request ID 追踪、启动会话列表与日志；资源隔离（`run_in_thread` + 并发闸门 + 扫描字节预算）。
> - **二期（已落地）**：进程级 `runId`；Python→Java `X-Request-ID` 透传；Java `RequestIdFilter` + `logback-spring.xml` JSONL；`runtime/{java,web,system}` 扫描；前端异常上报 `POST /diagnostics/frontend-events`；系统信息/系统事件/概览 API 与前端 Tab；清理脚本保留策略扩展。
> - **仍未做（非阻断）**：日志导出 `POST /export`、诊断包 `POST /bundles`、Loki/OpenSearch 后端、异常聚合聚类、OpenTelemetry `traceId`。

## 1. 文档概述

### 1.1 背景

Argus 项目当前由以下三个主要组成部分构成：

* Python 服务；
* Java 服务；
* Web 前端。

各组件分别产生运行日志，但日志来源、格式、存储目录和查看方式尚未完全统一。当系统出现接口异常、组件启动失败、模型调用超时、前端请求失败等问题时，技术人员需要分别查看多个日志文件，难以快速还原完整调用过程。

Argus 的主要部署方式包括：

* 技术人员本地部署；
* 公司内部单机私有化部署；
* 公司内部多节点私有化部署。

项目当前不依赖完整的用户中心、角色权限体系或多租户体系，因此本方案不建设以“用户行为审计”为核心的传统审计平台，而是建设面向开发、部署和运维人员的统一诊断能力。

### 1.2 建设定位

本模块统一命名为：

> **诊断中心**

诊断中心主要用于解决以下问题：

* 当前各组件是否正常运行；
* 哪个组件在什么时间出现异常；
* 一次请求经过了哪些组件；
* 某次启动会话中发生了什么；
* 前端、Java、Python 日志如何关联；
* 当前部署实例的版本、进程、端口和依赖状态；
* 技术人员如何快速获取完整故障上下文。

诊断中心不是传统意义上的安全审计系统，不承担复杂用户行为追踪、多租户审计或合规报表功能。

### 1.3 文档定位

* 本文是诊断中心的总体建设方案；现行日志体系的运行事实源是 [logging.md](../logging.md)。
* 两者关系：`logging.md` 描述“现在是什么”，本文描述“在此之上增建什么”。凡与 `logging.md` 冲突之处，必须先同步修订两份文档再实施，不允许各自漂移。
* 字段命名约定：日志 JSONL 落盘字段统一使用 camelCase（`requestId`、`runId`、`errorStack`），与现有 `JsonLogFormatter` 输出及前端 wire contract 保持一致；Python/Java 代码内部命名沿用各语言惯例（snake_case / camelCase）。
* 架构约束：Python 当前为单 worker/单副本（见 architecture.md），诊断查询属于同进程旁路负载，所有设计必须满足第 17 章的资源隔离约束。

### 1.4 现状盘点

以下能力已经存在。本方案是**增量建设**，不得重复实现：

| 能力 | 现状 | 位置 |
|------|------|------|
| Python 结构化 JSON 日志 | 已落地，含递归脱敏 | `argus_py.observability.logger` 的 `JsonLogFormatter` |
| request_id 生成/回传 | 中间件生成、响应头 `X-Request-ID` 回传、ContextVar 经线程池传播 | `observability/middleware.py`、`observability/context.py` |
| 四类文件 handler | app/error/audit/access 已拆分，RotatingFileHandler | `config/logging.yaml` |
| 敏感信息脱敏 | key=value、Authorization、JSON 字段递归脱敏已实现 | `argus_py.redaction` |
| 开发会话日志 | dev.mjs 写 `outputs/logs/dev/<run-id>/`（combined/python/java/frontend） | `scripts/dev.mjs` |
| 差异化清理 | dev 14 天/运行 30 天/错误 30 天/访问 14 天/审计 180 天 | `scripts/cleanup_outputs.py` |
| 前端异常捕获 | window.onerror、unhandledrejection、Vue errorHandler 已捕获并上报诊断中心 | `frontend/src/main.ts` → `POST /diagnostics/frontend-events` |
| JSONL 行索引先例 | 按 task_id 维护 `.idx` 侧车索引 | `observability/trace_index.py` |
| 诊断包雏形 | traces 打包 zip 的 debug bundle | `observability/debug_bundle.py` |
| Java 健康探针 | actuator health/info 已暴露 | `java_analyzer/src/main/resources/application.yml` |
| 跨服务 Request ID | Python `WhiteboxClient` 注入 `X-Request-ID`；Java Filter 写入 MDC 并回写响应头 | `whitebox/client.py`、`api/RequestIdFilter.java` |
| Java 结构化 JSONL | logback 滚动写入 `runtime/java/argus-java.jsonl` | `java_analyzer/.../logback-spring.xml` |
| 进程 runId | lifespan 初始化，日志白名单输出 `runId`；可经 `ARGUS_RUN_ID` 对齐 | `observability/context.py`、`logger.py` |
| 诊断查询 API / 前端页 | 概览/服务/日志/追踪/会话/系统事件/系统信息 | `api/routes/diagnostics.py`、`views/diagnostics/*` |

仍未建设（导出/诊断包/集中日志后端等）见文首实施状态。

---

## 2. 建设目标

### 2.1 总体目标

在不显著增加本地部署复杂度的前提下，为 Argus 建立统一、结构化、可检索、可关联的日志诊断能力。

### 2.2 具体目标

1. 统一 Python、Java、Web 三部分日志格式。
2. 建立统一的日志目录和生命周期管理规则。
3. 通过 `request_id` 关联一次请求涉及的全部组件日志。
4. 通过 `run_id` 关联一次启动会话产生的全部日志。
5. 在前端提供统一的日志查询、异常详情和服务状态页面。
6. 支持本地文件模式和集中式日志平台模式。
7. 默认适配本地部署，不强制依赖 Loki、Elasticsearch 等外部组件。
8. 为后续多节点私有化部署预留 Loki 等集中日志后端的扩展能力。
9. 对密钥、Token、请求头等敏感信息进行统一脱敏。
10. 提供日志清理、导出和诊断包生成能力。

---

## 3. 非建设范围

第一阶段不建设以下功能：

* 用户管理；
* 角色管理；
* 多租户日志隔离；
* 用户登录行为审计；
* 权限变更审计；
* 合规审计报表；
* 任意 SQL、LogQL 或 Elasticsearch DSL 查询；
* 海量日志长期归档；
* 完整 APM 性能监控平台；
* 完整分布式链路追踪平台；
* 浏览器所有 `console.log` 的集中采集。

后续如 Argus 接入统一身份认证，可在现有系统事件中补充操作来源信息，但不作为当前建设前提。

---

## 4. 总体架构

### 4.1 第一阶段架构

第一阶段采用轻量本地文件方案：

```text
Python 结构化日志 ───┐
                    │
Java 结构化日志 ─────┼──→ 本地 JSONL 日志文件
                    │
Web 前端异常上报 ────┘
                           ↓
                     LogRepository
                           ↓
                Argus 诊断查询后端接口
                           ↓
                      Web 诊断中心
```

该架构不额外引入日志数据库，适用于本地部署和单机私有化部署。

> 图中 LogRepository 泛指日志仓储，落地命名见 4.3（`DiagnosticsLogStore`）。

### 4.2 后续集中式架构

当公司内部出现多节点集中运维需求时，可扩展为：

```text
部署节点 A ── Agent ──┐
部署节点 B ── Agent ──┼──→ Loki
部署节点 C ── Agent ──┘
                           ↓
                  LokiDiagnosticsLogStore
                           ↓
               Argus 诊断查询后端接口
                           ↓
                     Web 诊断中心
```

前端页面和查询接口保持不变，仅替换日志数据源实现。

### 4.3 数据源抽象

后端定义统一日志仓储接口。**命名必须避开既有类**：`argus_py.task.repositories.log_repo.LogRepository`
是任务步骤日志存储，诊断日志仓储不得复用同名，统一命名为 `DiagnosticsLogStore`：

```python
class DiagnosticsLogStore:
    def search(self, query):
        pass

    def get_detail(self, event_id):
        pass

    def get_context(self, event_id, before, after):
        pass

    def search_by_request_id(self, request_id):
        pass

    def list_runs(self, query):
        pass

    def get_run_detail(self, run_id):
        pass
```

第一阶段实现：

```text
FileDiagnosticsLogStore
```

后续可增加：

```text
LokiDiagnosticsLogStore
OpenSearchDiagnosticsLogStore
```

上层业务接口不直接依赖具体日志平台；仓储实例在 `argus_py/runtime/container.py`
组合根组装，禁止在 route 或 service 内自行创建。

---

## 5. 功能模块设计

诊断中心建议包含以下模块：

```text
诊断中心
├── 概览
├── 服务状态
├── 运行日志
├── 请求追踪
├── 启动会话
├── 前端异常
├── 系统事件
└── 系统信息
```

---

## 6. 概览页面

### 6.1 页面目标

概览页面用于快速判断当前 Argus 是否处于健康状态，并展示近期主要异常。

### 6.2 展示内容

顶部状态卡片：

* Python 服务状态；
* Java 服务状态；
* Web 前端状态；
* 数据库连接状态；
* 模型服务连接状态；
* 当前启动会话；
* 当前日志目录占用空间。

近期统计：

* 最近一小时 ERROR 数量；
* 最近一小时 WARN 数量；
* Python 异常数量；
* Java 异常数量；
* 前端异常数量；
* 最近一次组件异常退出时间。

近期事件：

* 最近发生的 ERROR 日志；
* 最近发生的服务启动、停止和重启事件；
* 最近发生的前端未捕获异常。

### 6.3 页面原则

概览页面只展示摘要，不承担复杂日志检索功能。点击具体数据后跳转至对应详情页面并自动携带过滤条件。

---

## 7. 服务状态页面

### 7.1 页面目标

集中展示 Argus 各组件和依赖服务的运行状态。

### 7.2 展示字段

| 字段     | 说明                        |
| ------ | ------------------------- |
| 组件名称   | Python、Java、Web、数据库、模型服务等 |
| 状态     | 正常、异常、启动中、已停止、未知          |
| 版本     | 当前运行版本                    |
| PID    | 当前进程编号                    |
| 端口     | 当前监听端口                    |
| 启动时间   | 当前进程启动时间                  |
| 运行时长   | 当前组件连续运行时长                |
| 最近检查时间 | 最近一次健康检查时间                |
| 响应耗时   | 健康检查请求耗时                  |
| 异常摘要   | 健康检查失败原因                  |

### 7.3 健康检查来源

Python 服务：

```http
GET /health
GET /ready
```

Java 服务：

```http
GET /actuator/health
```

如果 Java 未启用 Spring Boot Actuator，可提供项目自定义健康检查接口。

Web 前端状态可通过以下方式判断：

* 前端静态资源是否可访问；
* 前端版本接口是否可访问；
* 当前浏览器与后端连接是否正常；
* WebSocket 是否正常连接。

### 7.4 扩展检查项

可选检查：

* SQLite 数据库连接；
* 模型网关（LLM）连接；
* 外部 API 连接；
* 磁盘剩余空间；
* 日志目录大小；
* 当前端口占用情况。

> 说明：Argus 当前不依赖 Redis 和独立消息队列（队列在 Python 进程内），
> 不设置对应检查项；架构变化时再补充。

---

## 8. 运行日志页面

### 8.1 页面目标

统一查询 Python、Java 和 Web 三部分运行日志。

### 8.2 查询条件

支持以下过滤项：

* 时间范围；
* 日志组件；
* 日志级别；
* 启动会话；
* 部署实例；
* 模块或类名；
* 关键词；
* `requestId`；
* 进程 PID；
* 主机名；
* 是否仅查看异常日志。

组件选项：

```text
全部
Python
Java
Web
Launcher
System
```

日志级别：

```text
TRACE
DEBUG
INFO
WARN
ERROR
FATAL
```

### 8.3 日志列表字段

| 字段         | 说明                         |
| ---------- | -------------------------- |
| 时间         | 精确到毫秒                      |
| 级别         | ERROR、WARN 等               |
| 组件         | Python、Java、Web            |
| 模块         | Python logger、Java 类名或前端模块 |
| 日志摘要       | 单行日志内容                     |
| Request ID | 请求关联标识                     |
| Run ID     | 启动会话标识                     |
| 实例         | 部署实例标识                     |

### 8.4 日志详情

点击日志后打开详情抽屉，展示：

* 日志时间；
* 日志级别；
* 组件；
* 模块；
* 主机名；
* 进程 PID；
* 线程名称；
* `runId`；
* `requestId`；
* 完整消息；
* 异常类型；
* 完整异常堆栈；
* 原始 JSON；
* 日志文件来源；
* 日志文件行号或偏移量。

提供以下操作：

* 复制日志；
* 复制异常堆栈；
* 复制 Request ID；
* 查看前后日志；
* 查看同一请求；
* 查看所属启动会话；
* 下载当前日志片段。

### 8.5 日志上下文

支持查看当前日志前后一定范围的日志：

```text
前 20 条
当前日志
后 20 条
```

或者按时间查询：

```text
当前日志前 10 秒
当前日志后 10 秒
```

上下文默认限定在同一组件、同一日志文件或同一启动会话内。

### 8.6 分页方式

日志查询应使用游标分页，不建议使用深度页码分页。

请求示例：

```http
GET /api/diagnostics/logs?limit=100&cursor=xxx
```

响应示例：

```json
{
  "items": [],
  "next_cursor": "xxx",
  "has_more": true
}
```

---

## 9. 请求追踪页面

### 9.1 页面目标

通过统一的 `request_id`，还原一次请求在 Web、Java 和 Python 之间的完整处理过程。

### 9.2 调用过程示例

```text
16:42:09.120 Web      发起 POST /api/tasks
16:42:09.186 Java     接收到请求
16:42:09.240 Java     开始调用 Python 服务
16:42:09.328 Python   接收到任务请求
16:42:10.904 Python   模型请求超时
16:42:10.930 Java     Python 服务返回 504
16:42:10.945 Java     向前端返回 500
16:42:10.981 Web      接口请求失败
```

### 9.3 页面展示

页面顶部输入：

```text
Request ID
```

结果以时间线形式展示：

* 时间；
* 组件；
* 事件类型；
* 日志级别；
* 摘要；
* 接口路径；
* HTTP 状态码；
* 耗时；
* 异常信息。

### 9.4 Request ID 生成和传递

推荐由请求链路最外层生成 `request_id`。

浏览器请求：

```http
X-Request-ID: req-xxxxxxxx
```

如果浏览器未生成，则由最先接收到请求的后端生成。

Java 调用 Python 时继续传递：

```http
X-Request-ID: req-xxxxxxxx
```

后端响应同样返回：

```http
X-Request-ID: req-xxxxxxxx
```

Web、Java、Python 三部分日志必须记录相同的 `request_id`。

### 9.5 Trace ID

第一阶段以 `request_id` 为主要关联标识。

如果后续接入 OpenTelemetry，可增加：

```text
trace_id
span_id
parent_span_id
```

`request_id` 用于业务和技术人员检索，`trace_id` 用于标准分布式调用链追踪。

---

## 10. 启动会话页面

### 10.1 页面目标

通过 `run_id` 关联一次 Argus 启动过程产生的全部日志。

### 10.2 Run ID 定义

每次通过启动器启动 Argus 时生成唯一 `run_id`：

```text
20260805-162001-a7f3
```

推荐格式：

```text
yyyyMMdd-HHmmss-随机后缀
```

生成与传递责任（按启动方式区分，避免“run_id 从哪来”无定义）：

* dev.mjs 启动：由启动器生成，作为 dev 会话目录名，并写入 `session.json`；
* Docker 部署：由启动脚本生成并通过环境变量（如 `ARGUS_RUN_ID`）注入各组件；
* systemd / 服务脚本直启：由包装脚本生成注入；未注入时 Python 服务启动时自行生成回退值并在日志中标注来源；
* 单组件独立重启（如只重启 Java）：Java 读取环境变量继承当前 run_id，读不到时自生成并记录系统事件。

### 10.3 启动会话信息

| 字段         | 说明                    |
| ---------- | --------------------- |
| Run ID     | 启动会话唯一标识              |
| 开始时间       | 启动时间                  |
| 结束时间       | 停止时间                  |
| 状态         | 启动中、运行中、部分失败、已停止、异常退出 |
| 启动方式       | dev.mjs、Docker、服务脚本等  |
| 主机名        | 部署机器                  |
| 工作目录       | 启动工作目录                |
| Python PID | Python 进程             |
| Java PID   | Java 进程               |
| Web PID    | 前端进程                  |
| 启动参数       | 脱敏后的启动参数              |
| 版本信息       | 各组件版本                 |

### 10.4 启动会话详情

展示以下内容：

```text
启动会话
├── 启动器日志
├── Python 标准输出
├── Python 标准错误
├── Java 标准输出
├── Java 标准错误
├── Web 标准输出
├── Web 标准错误
└── 会话系统事件
```

### 10.5 会话状态判断

启动器应记录：

* 各进程启动时间；
* 各进程 PID；
* 各进程退出码；
* 各进程停止原因；
* 启动检查结果；
* 健康检查结果。

当任一核心组件启动失败时，会话状态标记为：

```text
部分失败
```

当进程非正常退出时，会话状态标记为：

```text
异常退出
```

---

## 11. 前端异常页面

### 11.1 采集范围

前端仅采集具有诊断价值的异常，不采集全部 `console.log`。

建议采集：

* `window.onerror`；
* `unhandledrejection`；
* Vue 全局错误；
* React Error Boundary 错误；
* HTTP 请求失败；
* WebSocket 异常断开；
* 静态资源加载失败；
* 关键业务任务执行失败；
* 页面白屏；
* 应用初始化失败。

### 11.2 不建议采集

默认不采集：

* 普通调试日志；
* 用户输入的完整内容；
* 页面完整 HTML；
* Cookie；
* LocalStorage 全量内容；
* Authorization 请求头；
* 表单密码；
* API Key；
* 文件内容。

### 11.3 上报接口

```http
POST /api/diagnostics/frontend-events
```

支持批量上报：

```json
{
  "events": [
    {
      "timestamp": "2026-08-05T16:42:09.120+08:00",
      "level": "ERROR",
      "eventType": "api_error",
      "message": "Request failed with status 500",
      "page": "/tasks/1024",
      "apiPath": "/api/tasks/:id",
      "httpStatus": 500,
      "durationMs": 2381,
      "requestId": "req-82ab",
      "release": "2026.08.05",
      "browser": "Edge 151"
    }
  ]
}
```

### 11.4 上报控制

服务端应实施：

* 单次事件数量限制；
* 单条日志长度限制；
* 请求频率限制；
* 重复错误合并；
* 日志字段白名单；
* 敏感字段脱敏；
* 非法字符清洗；
* 超大堆栈截断；
* 来源校验；
* 鉴权与现有 API Token 机制对齐，浏览器场景无法携带凭证时的豁免必须配合来源校验与更严格的限流；
* 上报失败静默降级，不得重试风暴、不得影响页面运行。

### 11.5 重复异常聚合

可根据以下字段生成异常指纹：

```text
eventType
errorType
message
stackTop
page
release
```

相同异常短时间重复出现时，可合并展示：

```text
TypeError: Cannot read properties of undefined
最近出现：16:42:09
首次出现：15:18:20
出现次数：126
```

第一阶段可以只保存原始事件，异常聚合作为后续优化功能。

---

## 12. 系统事件页面

### 12.1 模块定位

系统事件用于记录重要的运行状态变化，不等同于普通日志，也不依赖用户体系。

实现上必须复用既有机制，**不建立第二套事件管道**：

* Python 侧复用 `audit()` / EventBus 与结构化事件日志 `log_event()`，系统事件页面对既有事件流做检索投影；
* 启动器与部署层事件由启动器写入会话文件，经诊断后端聚合展示；
* 禁止业务代码为诊断中心另行埋设独立事件写入通道。

### 12.2 事件范围

建议记录：

* Argus 启动；
* Argus 停止；
* 组件启动成功；
* 组件启动失败；
* 组件异常退出；
* 组件重启；
* 配置重新加载；
* 配置加载失败；
* 数据库迁移；
* 日志轮转；
* 日志清理；
* 诊断包生成；
* 模型服务切换；
* 端口占用；
* 磁盘空间不足；
* 外部依赖不可用；
* 系统版本升级。

### 12.3 数据结构

```json
{
  "eventId": "evt-01J...",
  "timestamp": "2026-08-05T16:20:01.321+08:00",
  "eventType": "service.started",
  "component": "argus-python",
  "runId": "20260805-162001-a7f3",
  "instanceId": "argus-local-desktop-01",
  "result": "success",
  "source": "launcher",
  "details": {
    "pid": 10324,
    "port": 8000,
    "version": "1.4.2"
  }
}
```

### 12.4 操作来源

虽然当前没有用户体系，但可保留通用来源字段：

```text
system
launcher
local-ui
command-line
scheduler
remote-api
```

如果后续接入统一身份认证，可增加：

```text
operator
operator_id
```

现阶段不强制依赖。

---

## 13. 系统信息页面

### 13.1 页面目标

集中展示部署环境信息，减少远程排障时反复询问环境参数。

### 13.2 展示内容

* Argus 总版本；
* Python 服务版本；
* Java 服务版本；
* Web 前端版本；
* Git Commit ID；
* 构建时间；
* 操作系统；
* 系统架构；
* Python 版本；
* Java 版本；
* Node.js 版本；
* 主机名；
* CPU 核心数；
* 内存容量；
* 可用内存；
* 磁盘总容量；
* 磁盘剩余空间；
* 当前工作目录；
* 日志目录；
* 数据目录；
* 配置文件路径；
* 当前部署模式；
* 当前日志数据源。

涉及路径、IP 和环境变量时，应根据部署环境进行适当隐藏或脱敏。

---

## 14. 日志规范

### 14.1 日志格式

所有组件的结构化日志统一采用 JSON Lines 格式：

```text
一行一个 JSON 对象
编码：UTF-8
```

扩展现状说明：`outputs/logs/runtime/python/` 下现有文件继续使用 `.log`
扩展名（`argus.log`、`argus.error.log` 等，内容已是 JSON Lines），不统一改名为
`.jsonl`，避免破坏既有 handler 与清理规则；新增日志类别（前端异常、系统事件）
采用 `.jsonl` 扩展名。

### 14.2 通用字段

落盘字段名统一 camelCase，与现有 `JsonLogFormatter` 输出（`requestId`、`taskId`、
`durationMs`）及前端 wire contract 保持一致。所有组件应尽量输出以下字段：

```json
{
  "timestamp": "2026-08-05T16:31:22.153+08:00",
  "level": "ERROR",
  "service": "argus-python",
  "component": "python",
  "environment": "local",
  "instanceId": "argus-local-desktop-01",
  "host": "DESKTOP-ABC123",
  "pid": 10324,
  "thread": "MainThread",
  "logger": "argus.llm.gateway",
  "message": "Upstream request failed",
  "runId": "20260805-162001-a7f3",
  "requestId": "req-82ab",
  "errorType": "TimeoutError",
  "errorStack": "..."
}
```

`instanceId` 在单机部署下默认取主机名或配置值，多节点部署时由部署脚本注入。
`traceId` / `spanId` 第一阶段不进入通用字段（见 9.5）。

### 14.3 必填字段

第一阶段必填：

```text
timestamp
level
service
component
message
```

运行期推荐必填：

```text
instanceId
host
pid
runId
```

请求日志推荐必填：

```text
requestId
```

### 14.4 服务命名

统一服务名称：

```text
argus-python
argus-java
argus-web
argus-launcher
argus-system
```

不得在不同组件中混用：

```text
python-server
py-service
backend-python
argus-py
```

### 14.5 时间规范

所有日志内部统一使用带时区的 ISO 8601 格式：

```text
2026-08-05T16:31:22.153+08:00
```

建议同时保留毫秒精度。

不同机器必须进行时间同步，否则跨组件日志排序可能不准确。

---

## 15. 日志目录设计

目录结构以现有布局为基线扩展（不迁移、不改名既有文件）：

```text
outputs/logs/
├── dev/
│   └── <run-id>/
│       ├── session.json        # 新增：run_id、启动方式、PID、版本等会话元数据
│       ├── combined.log        # 现有（dev.mjs）
│       ├── python.log          # 现有（dev.mjs）
│       ├── java.log            # 现有（dev.mjs）
│       └── frontend.log        # 现有（dev.mjs）
│
├── runtime/
│   ├── python/                 # 现有四类 JSON Lines 文件，保持不变
│   │   ├── argus.log
│   │   ├── argus.error.log
│   │   ├── argus.access.log
│   │   └── argus.audit.log
│   ├── web/
│   │   └── frontend-events.jsonl   # 新增：前端异常上报
│   └── system/
│       └── events.jsonl            # 新增：系统事件
│
└── archive/
```

### 15.1 开发会话日志

```text
outputs/logs/dev/<run-id>/
```

用于保存某次启动过程中各进程的原始输出。沿用 dev.mjs 现有四文件布局
（combined/python/java/frontend），**不**改为 stdout/stderr 八文件拆分；
`session.json` 为本次方案新增的会话元数据文件。

### 15.2 运行时结构化日志

```text
outputs/logs/runtime/
```

用于诊断中心检索，必须采用统一结构化格式。

### 15.3 两类日志的关系

开发会话日志用于保留原始启动过程。

运行时结构化日志用于统一检索和关联。

二者可以包含部分重复信息，但用途不同，不应混合在同一目录层级。

---

## 16. 日志轮转和保留策略

### 16.1 默认策略

保留策略的**唯一事实来源**是 `config/logging.yaml`（轮转参数）和
`scripts/cleanup_outputs.py`（清理阈值）。本表与其保持一致，新增日志类别
必须同步登记清理规则（见 logging.md「修改 config/logging.yaml 的原则」）：

| 日志类型     | 轮转配置（logging.yaml） | 清理阈值（cleanup_outputs.py） |
| -------- | ------------------- | ------------------------ |
| 运行日志     | 10 MB × 20 备份       | 30 天                     |
| 错误日志     | 10 MB × 20 备份       | 30 天                     |
| 访问日志     | 10 MB × 20 备份       | 14 天                     |
| 审计日志     | 10 MB × 10 备份       | 180 天                    |
| 前端异常（新增） | 建议 20 MB × 10 备份    | 14 天                     |
| 系统事件（新增） | 建议 20 MB × 10 备份    | 90 天                     |
| 开发会话日志   | 按会话                 | 14 天                     |

> 注意：保留期是清理上限，实际可用时长受 RotatingFileHandler 的
> maxBytes/backupCount 约束；不得在本方案中另设一套与上述文件冲突的数字。

### 16.2 清理规则

同时满足以下任一条件时触发清理：

* 超过保留天数；
* 超过目录最大容量；
* 磁盘剩余空间低于阈值。

清理优先级：

1. 最旧开发会话；
2. 最旧 DEBUG 日志；
3. 最旧 INFO 日志；
4. 最旧 WARN 日志；
5. 最旧 ERROR 日志。

系统事件和最近一次启动会话应尽量最后清理。

### 16.3 配置化

保留策略参数化时收敛进现有配置体系（`config/logging.yaml` /
`config/server.yaml`），不另建第二套配置文件；默认值与 16.1 一致：

```yaml
diagnostics:
  logs:
    retention:
      runtime_days: 30      # 与 cleanup_outputs.py 现值一致
      error_days: 30
      access_days: 14
      audit_days: 180
      run_days: 14          # dev 会话，现值
      frontend_events_days: 14
      system_events_days: 90
      max_total_size_mb: 4096
```

---

## 17. 后端接口设计

所有 `/api/diagnostics/*` 查询接口必须遵守以下约束（源于单 worker/单副本架构硬约束，见 architecture.md）：

* 查询逻辑一律在线程池中执行（沿用路由层 `run_in_thread` 惯例），禁止在事件循环内扫描文件；
* 每类查询设置并发上限与显式超时，超限快速返回 429/503，不排队堆积；
* 强制 `limit` 上限与游标分页，禁止全量返回；
* 单次扫描的文件字节上限可配置，按实际读取字节严格截断，超限时提示缩小时间范围；
* 文件仓储的新事件 ID/游标使用“相对路径 + 字节偏移 + 时间戳”的不透明定位器，
  服务端继续兼容旧行号格式；轮转或截断使精确位置失效时按时间戳降级续页；
* 诊断仓储实例在组合根（`argus_py/runtime/container.py`）组装，route/service 不得自行创建。

### 17.1 概览接口

```http
GET /api/diagnostics/overview
```

返回：

* 服务状态摘要；
* 最近错误数量；
* 当前启动会话；
* 日志空间占用；
* 最近系统事件。

### 17.2 服务状态接口

```http
GET /api/diagnostics/services
```

### 17.3 日志查询接口

```http
GET /api/diagnostics/logs
```

参数：

```text
from
to
component
level
keyword
requestId
runId
instanceId
module
limit
cursor
```

> 查询参数第一阶段不含 `traceId`（OpenTelemetry 接入后再扩展，见 9.5）；
> 参数命名在落地时遵循项目 OpenAPI wire contract 惯例。

### 17.4 日志详情接口

```http
GET /api/diagnostics/logs/{eventId}
```

### 17.5 日志上下文接口

```http
GET /api/diagnostics/logs/{eventId}/context
```

参数：

```text
before
after
```

### 17.6 请求追踪接口

```http
GET /api/diagnostics/requests/{requestId}
```

### 17.7 启动会话接口

```http
GET /api/diagnostics/runs
GET /api/diagnostics/runs/{runId}
GET /api/diagnostics/runs/{runId}/logs
```

### 17.8 前端异常上报接口

```http
POST /api/diagnostics/frontend-events
```

### 17.9 系统事件接口

```http
GET /api/diagnostics/events
```

### 17.10 系统信息接口

```http
GET /api/diagnostics/system
```

### 17.11 日志导出接口

```http
POST /api/diagnostics/export
```

请求参数：

```json
{
  "from": "2026-08-05T16:00:00+08:00",
  "to": "2026-08-05T17:00:00+08:00",
  "components": ["python", "java", "web"],
  "levels": ["WARN", "ERROR"],
  "requestId": null,
  "runId": null
}
```

### 17.12 诊断包接口

```http
POST /api/diagnostics/bundles
GET /api/diagnostics/bundles/{bundleId}
```

诊断包可包含：

* 指定时间范围内的日志；
* 当前服务状态；
* 系统信息；
* 脱敏后的配置摘要；
* 当前启动会话信息；
* 版本信息；
* 最近系统事件。

---

## 18. 文件日志查询实现

### 18.1 第一阶段查询方式

后端直接扫描 JSONL 文件并解析日志。

为避免每次查询读取全部文件，应维护轻量索引信息：

* 文件起止时间；
* 文件大小；
* 最后修改时间；
* 组件；
* 日志级别；
* 行数；
* 首条日志时间；
* 末条日志时间。

索引可以保存在：

```text
outputs/logs/.index/
```

或者存入 SQLite。

### 18.2 SQLite 辅助索引

建议仅将日志元数据写入 SQLite，而不是将全部日志重复写入数据库。

示例表：

```sql
CREATE TABLE log_file_index (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    component TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    file_size INTEGER NOT NULL,
    modified_time TEXT NOT NULL,
    line_count INTEGER
);
```

如需提升 Request ID 查询性能，可额外建立轻量事件索引：

```sql
CREATE TABLE log_event_index (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    component TEXT NOT NULL,
    level TEXT NOT NULL,
    request_id TEXT,
    run_id TEXT,
    file_path TEXT NOT NULL,
    byte_offset INTEGER NOT NULL
);
```

是否建立事件级索引可根据实际日志量决定。

事件级索引的实现约束：

* 参考既有 `observability/trace_index.py` 的侧车索引经验：索引是**可重建的派生缓存，不是事实源**；
* `byte_offset` 只对特定文件代次有效：文件轮转或被清理后，对应索引条目必须失效，按 `file_path + modified_time` 判断；
* JSONL 与 SQLite 双写不引入分布式事务：以 JSONL 为准；索引缺失或可疑时降级为受限扫描并异步重建；
* 首次查询命中未建索引的时间范围时，限制单次扫描字节数上限，避免长尾查询拖垮单 worker 服务；
* 索引写入与查询同受第 17 章资源隔离约束。

### 18.3 文件安全

查询接口只能访问配置允许的日志根目录。

必须拒绝：

* `../` 路径穿越；
* 任意绝对路径；
* 用户直接指定文件路径；
* 符号链接逃逸；
* 非日志文件访问。

---

## 19. 敏感信息处理

脱敏能力已在 `argus_py.redaction` 实现并被 `JsonLogFormatter` 递归应用。
诊断中心的所有出口（查询、导出、诊断包）**必须复用同一模块**，不得另写一套
脱敏正则；Java 侧提供等价 filter 并与 Python 规则用同一份测试用例约束。

### 19.1 禁止记录内容

以下内容禁止写入日志：

* 明文密码；
* API Key；
* Access Token；
* Refresh Token；
* Session ID；
* Cookie；
* Authorization 请求头；
* 数据库密码；
* 私钥；
* 完整连接字符串；
* 用户上传文件完整内容；
* 未经处理的敏感请求体；
* 完整环境变量。

### 19.2 脱敏规则

示例：

```text
sk-1234567890abcdef
→ sk-****cdef
```

```text
Authorization: Bearer eyJhbGci...
→ Authorization: Bearer ***
```

```text
postgresql://user:password@host/db
→ postgresql://user:***@host/db
```

### 19.3 字段白名单

请求日志应优先采用字段白名单，而不是先记录全部请求再删除敏感字段。

例如允许：

```text
method
path
statusCode
durationMs
requestId
contentLength
```

默认不记录：

```text
headers
body
query_string 全量内容
```

### 19.4 日志注入防护

写入日志前应处理：

* 回车；
* 换行；
* 制表符；
* 控制字符；
* 超长字符串；
* 非法 Unicode 字符。

原始异常堆栈允许包含换行，但必须作为 JSON 字符串正确转义。

---

## 20. 访问控制

虽然当前没有用户体系，仍应限制诊断接口的暴露范围。

诊断接口的鉴权必须与现有 API 鉴权机制（API Token）保持一致，**不另建第二套
认证体系**；确需豁免（如浏览器页面场景）时，豁免范围仅限只读查询类接口，
写入与导出类接口不得豁免。

### 20.1 本地部署

默认仅允许：

```text
127.0.0.1
localhost
```

访问诊断接口。

### 20.2 私有化部署

建议通过以下任一方式保护：

* 内网访问限制；
* 反向代理基础认证；
* 部署级诊断 Token；
* 公司统一网关认证；
* VPN 或零信任网络访问。

### 20.3 高风险功能

以下功能应默认关闭或额外保护：

* 下载完整日志；
* 生成诊断包；
* 查看原始 JSON；
* 查看系统路径；
* 查看环境摘要；
* 清理日志；
* 手动触发服务重启。

诊断页面不应提供任意命令执行能力。

---

## 21. 前端交互设计

### 21.1 自动刷新

运行日志支持：

```text
关闭
5 秒
10 秒
30 秒
```

自动刷新时应使用增量游标获取新日志，不应重复查询整个时间范围。

### 21.2 实时日志

第一阶段可通过短轮询实现。

后续如确有需要，可增加：

```text
Server-Sent Events
WebSocket
```

不建议第一版直接建设复杂实时日志流。

### 21.3 日志显示

日志列表应支持：

* 单行截断；
* 展开完整内容；
* 级别高亮；
* 关键词高亮；
* 等宽字体；
* 自动换行开关；
* 时间显示格式切换；
* 本地时区展示；
* 复制功能。

### 21.4 大日志保护

前端应限制：

* 单页最大日志条数；
* 单条详情最大展示长度；
* 最大异常堆栈长度；
* 最大查询时间跨度；
* 最大导出数据量。

---

## 22. 部署模式

### 22.1 Local 模式

适用于技术人员本地开发。

特点：

* 使用本地日志文件；
* 默认仅本机可访问；
* 自动识别开发启动会话；
* 保留时间较短；
* 支持查看原始标准输出。

配置示例：

```yaml
diagnostics:
  enabled: true
  mode: local
  log_repository: file
  bind_scope: localhost
```

### 22.2 Standalone 模式

适用于公司内部单机私有化部署。

特点：

* 使用本地日志文件；
* 支持内网访问；
* 保留时间更长；
* 支持诊断包；
* 支持基础访问保护。

```yaml
diagnostics:
  enabled: true
  mode: standalone
  log_repository: file
  bind_scope: intranet
```

### 22.3 Centralized 模式

适用于多节点集中部署。

特点：

* 使用 Loki 等集中日志后端；
* 支持实例筛选；
* 支持跨节点查询；
* 支持较长时间范围；
* 前端接口保持不变。

```yaml
diagnostics:
  enabled: true
  mode: centralized
  log_repository: loki
  loki:
    endpoint: http://loki:3100
```

---

## 23. 实施阶段

### 第一阶段：日志基础规范

目标：在现有基础上补齐跨组件关联能力。Python 侧大部分已完成（见 1.4 现状盘点），
本阶段聚焦真正的缺口。

已完成（仅核对，不重建）：

* Python JSONL 结构化日志、request_id 生成/回传、四类 handler、脱敏；
* dev 会话目录与差异化清理脚本。

工作内容：

1. 核对 Python 日志字段与本方案 14.2 一致（camelCase）；
2. **Java 日志 JSONL 化**（独立子任务，工作量最大）：
   * 引入 logback JSON encoder（如 logstash-logback-encoder 或等价物）；
   * 通过 MDC 贯通 `requestId` / `runId`；
   * `WhiteboxClient` 调用 Java 时注入 `X-Request-ID`，Java 侧中间件读取并写入 MDC；
3. 定义 Web 异常事件结构（camelCase，与 11.3 一致）；
4. 核对各服务名称符合 14.4；
5. 补齐 `run_id` 生成与注入链路（见 10.2 按部署方式区分的责任）；
6. dev 会话目录新增 `session.json`；
7. Java 侧提供与 `argus_py.redaction` 等价的脱敏 filter；
8. 新增日志类别（前端异常、系统事件）并在 `cleanup_outputs.py` 登记清理规则。

交付结果：

* 三部分日志格式统一；
* 一次请求的 Request ID 从浏览器贯通到 Java 与 Python；
* 单次启动可以通过 Run ID 关联；
* 日志目录结构稳定且与 logging.md 一致。

### 第二阶段：诊断后端接口

目标：完成本地日志查询能力。

工作内容：

1. 实现 `DiagnosticsLogStore` 接口（命名避开既有任务步骤日志
   `task.repositories.log_repo.LogRepository`，见 4.3）；
2. 实现 `FileDiagnosticsLogStore`；
3. 实现日志搜索接口；
4. 实现日志详情接口；
5. 实现日志上下文接口；
6. 实现请求追踪接口；
7. 实现启动会话接口；
8. 实现服务状态接口；
9. 实现前端异常上报接口；
10. 实现系统信息接口；
11. 所有查询接口落实第 17 章资源隔离约束（线程池执行、并发上限、超时、limit 上限）。

交付结果：

* 前端可通过统一 API 查询三部分日志；
* 不需要直接读取服务器文件；
* 支持按组件、级别、时间和 Request ID 查询。

### 第三阶段：诊断中心前端

目标：提供完整可用的诊断页面。

工作内容：

1. 实现概览页面。
2. 实现服务状态页面。
3. 实现运行日志页面。
4. 实现日志详情抽屉。
5. 实现请求追踪页面。
6. 实现启动会话页面。
7. 实现前端异常页面。
8. 实现系统事件页面。
9. 实现系统信息页面。

交付结果：

* 技术人员可以在一个页面完成常见故障定位；
* 不再需要分别登录服务器查看三套日志。

### 第四阶段：导出和诊断包

目标：提高远程排障效率。

工作内容：

1. 日志片段导出；
2. 诊断包生成（基于既有 `observability/debug_bundle.py` 的 zip 打包扩展，纳入日志片段与服务状态快照）；
3. 脱敏配置摘要；
4. 系统状态快照；
5. 诊断包大小限制；
6. 诊断包自动清理。

### 第五阶段：集中式日志扩展

触发条件：

* 出现多节点部署；
* 单机日志量明显增长；
* 需要跨机器查询；
* 需要较长时间保存；
* 文件扫描性能不足。

工作内容：

1. 接入 Loki；
2. 实现 `LokiDiagnosticsLogStore`；
3. 增加实例和节点筛选；
4. 增加 Grafana 深链接；
5. 保持现有前端和 API 契约不变。

---

## 24. 第一版最小可用范围

第一版建议仅实现以下能力：

```text
诊断中心
├── 服务状态
├── 运行日志
├── 请求追踪
└── 启动会话
```

第一版必要查询条件：

* 时间范围；
* 组件；
* 日志级别；
* 关键词；
* Request ID；
* Run ID。

第一版必要详情：

* 完整日志；
* 异常堆栈；
* 原始 JSON；
* 前后上下文；
* 同一请求日志；
* 同一启动会话日志。

第一版暂不实现：

* Loki；
* 复杂图表；
* 实时 WebSocket 日志；
* 异常智能聚合；
* 全量诊断包；
* 远程服务控制；
* 复杂访问权限系统。

---

## 25. 验收标准

### 25.1 日志规范验收

* Python、Java、Web 日志均具有统一时间格式。
* Python、Java、Web 日志均包含明确组件标识。
* Python 和 Java 请求日志均记录 `request_id`。
* 一次完整调用中的 Request ID 保持一致。
* 启动器生成唯一 `run_id`。
* 各组件日志可以关联到启动会话。
* 敏感字段不会以明文出现在日志中。

### 25.2 查询功能验收

* 可以按时间范围查询日志。
* 可以按组件筛选日志。
* 可以按日志级别筛选。
* 可以通过关键词搜索日志。
* 可以通过 Request ID 查询完整调用过程。
* 可以查看日志前后上下文。
* 可以查看完整异常堆栈。
* 可以查看指定启动会话的全部日志。

### 25.3 性能验收

指标统一按以下基准测量：约 1 万行（约 10 MB）JSONL、无事件级索引的冷启动查询。

建议第一阶段指标：

* 查询最近一小时日志，首次响应不超过 2 秒；
* 普通条件查询不超过 3 秒；
* Request ID 精确查询不超过 2 秒；
* 单次返回日志不超过 200 条；
* 日志页面不会一次性加载完整日志文件；
* 前端异常上报不阻塞主要业务流程；
* 日志写入失败不得导致核心业务请求失败。

隔离验收（单 worker 架构保护）：

* 诊断查询持续进行时，核心业务接口 P95 耗时增幅不超过 20%；
* 任一诊断查询超时或失败，不影响业务请求处理。

### 25.4 稳定性验收

* 单个损坏日志行不会导致整个查询失败；
* 日志文件轮转期间查询接口可继续工作；
* 日志目录不存在时返回明确状态；
* 日志目录不可写时产生系统事件；
* 磁盘空间不足时触发告警或系统事件；
* 前端上报接口异常不会产生无限重试。

### 25.5 安全验收

* 无法通过接口读取日志目录外的文件；
* 日志查询接口不接受任意文件路径；
* 日志中不包含明文密码和 Token；
* 下载和导出具有大小限制；
* 诊断接口不会暴露任意命令执行能力；
* 私有化部署时诊断接口不会默认暴露到公网。

---

## 26. 风险与应对

### 26.1 文件扫描性能下降

风险：

日志量增长后，直接扫描 JSONL 文件可能变慢。

应对：

* 按日期和大小轮转；
* 限制查询时间范围；
* 使用游标分页；
* 建立 SQLite 辅助索引；
* 查询与业务请求资源隔离（见第 17 章），扫描变慢时降级限流而不是拖垮服务；
* 达到阈值后切换 Loki。

### 26.2 日志字段不一致

风险：

Python、Java 和 Web 各自定义字段，导致统一查询困难。

应对：

* 建立统一日志字段文档；
* 提供各语言日志封装；
* 对字段名称进行自动化测试；
* 禁止业务模块自行定义重复语义字段。

### 26.3 敏感信息泄漏

风险：

异常堆栈、请求参数和配置内容可能包含密钥。

应对：

* 日志入口统一脱敏；
* 字段白名单；
* 请求体默认不记录；
* 导出时再次脱敏；
* 增加敏感信息自动扫描测试。

### 26.4 Request ID 未贯通

风险：

某些内部调用未传递 Request ID，导致调用链断裂。

应对：

* 在 Java 和 Python HTTP 客户端层统一注入；
* 在服务端中间件统一生成；
* 响应头统一返回；
* 增加集成测试验证。

### 26.5 前端异常上报形成日志风暴

风险：

前端循环异常可能短时间上报大量事件。

应对：

* 浏览器端限流；
* 服务端限流；
* 相同错误去重；
* 单页面最大上报次数限制；
* 超限后只记录统计信息。

---

## 27. 最终建议

Argus 当前最适合采用以下建设路线：

```text
统一 JSON 结构化日志
        +
统一 Request ID
        +
统一 Run ID
        +
本地文件日志仓储
        +
Web 诊断中心
```

第一阶段不直接引入 Loki、Elasticsearch 或 OpenSearch，避免增加本地部署复杂度。

系统设计上必须保留日志仓储抽象，使本地部署使用 `FileDiagnosticsLogStore`，多节点私有化部署可以切换至 `LokiDiagnosticsLogStore`。

实施过程中本方案与 [logging.md](../logging.md) 同步演进：凡日志字段、handler、
保留策略的变更，先更新 `logging.md` 再落地代码；两者冲突时以先完成的双文档
同步修订为准。

最终形成以下产品结构：

```text
诊断中心
├── 概览
├── 服务状态
├── 运行日志
├── 请求追踪
├── 启动会话
├── 前端异常
├── 系统事件
└── 系统信息
```

该方案能够满足 Argus 当前本地部署和公司内部私有化部署的主要排障需求，同时不会过早引入复杂用户体系和重量级日志基础设施，并为后续集中式日志管理保留清晰的升级路径。
