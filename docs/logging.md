# Argus 日志体系

> 新增日志埋点或修改 `config/logging.yaml` 前请先阅读本文。

本文档覆盖以下内容：

- [日志命名空间（logger 名称）](#日志命名空间)
- [Handler 拆分与路由](#handler-拆分与路由)
- [日志格式](#日志格式)
- [上下文字段注入](#上下文字段注入)
- [`audit()` — 业务审计日志](#audit--业务审计日志)
- [`log_event()` — 结构化事件日志](#log_event--结构化事件日志)
- [`@log_operation` — 方法执行切面](#log_operation--方法执行切面)
- [CLI 输出分层](#cli-输出分层)
- [敏感数据脱敏](#敏感数据脱敏)
- [第三方库降噪](#第三方库降噪)

---

## 日志命名空间

项目配置了两组 logger 命名树：

### `argus_py.xxx`（模块命名空间）

以 `logging.getLogger(__name__)` 获取的 logger 自动挂在 `argus_py` 树下：

```
argus_py
├── api.app
├── blackbox.execution_loop
├── blackbox.runner
├── cli.main
├── infra.db
├── infra.events
├── infra.worker
├── llm.client
├── observability.aspect
├── task.lifecycle
└── ...
```

### `argus.xxx`（功能命名空间）

专有 logger 用于跨模块的独立日志流：

| Logger | 用途 | Handler |
|--------|------|---------|
| `argus.audit` | 业务审计日志（用户可感知的操作） | console + audit_file |
| `argus.request` | 请求访问日志 | access_file |
| `argus.operation` | `@log_operation` 装饰器的执行轨迹 | app_file（通过 propagate） |

### 命名规范

- 新 logger 一律用 `logging.getLogger(__name__)` 自动挂到 `argus_py` 树下
- 不要在模块内硬编码 logger 名字符串
- 功能 logger（`argus.audit` 等）在 `config/logging.yaml` 中注册

---

## Handler 拆分与路由

```
                        ┌──────────────┐
                        │  logger 调用   │
                        └──────┬───────┘
                               │
                ┌──────────────┼──────────────────┐
                │              │                  │
         argus_py         argus.audit        argus.request
         propagate:false  propagate:false    propagate:false
                │              │                  │
         ┌──────┴──────┐      │                  │
         │             │      │                  │
    app_file      console  audit_file        access_file
    (DEBUG)       (INFO)   (INFO)            (DEBUG)
    JSON          文本      JSON              JSON
    Rotating      stdout   Rotating          Rotating
         │             │
    error_file    error_file
    (ERROR)       (ERROR, propagate)
    JSON          JSON
```

| Handler | 级别 | 格式 | 保存 | 适用场景 |
|---------|------|------|------|----------|
| `console` | INFO | 人类可读 + 链路字段 | stdout | 容器日志 `docker logs`、开发调试 |
| `app_file` | DEBUG | JSON | `outputs/logs/runtime/python/argus.log` | 全量结构化日志，ELK / 离线排查 |
| `error_file` | ERROR | JSON | `outputs/logs/runtime/python/argus.error.log` | 告警对接、ERROR 独立检索 |
| `audit_file` | INFO | JSON | `outputs/logs/runtime/python/argus.audit.log` | 审计事件只写此文件 |
| `access_file` | DEBUG | JSON | `outputs/logs/runtime/python/argus.access.log` | HTTP 访问日志 |

所有文件 handler 使用 `RotatingFileHandler`，单文件 10MB，保留 20 个备份
（audit_file 保留 10 个）。

### 日志目录布局

```text
outputs/logs/
├── dev/<run-id>/              # 开发会话（dev.mjs）
│   ├── combined.log
│   ├── python.log
│   ├── frontend.log
│   └── java.log
└── runtime/python/            # Python 运行时结构化日志
    ├── argus.log              # 当前文件（受保护，清理脚本不删除）
    ├── argus.log.1            # 轮转文件（清理脚本按类别删除）
    ├── argus.error.log
    ├── argus.audit.log
    └── argus.access.log
```

### 清理保留策略

`scripts/cleanup_outputs.py` 对 `logs` 目标按文件路径使用差异化保留期：

| 类别 | 路径 | 清理阈值 | 说明 |
|------|------|---------|------|
| 开发会话 | `logs/dev/<run-id>/**` | 14 天 | 按文件 mtime 分别清理 |
| 普通运行（轮转） | `argus.log.N[.gz]` | 30 天 | 故障排查 |
| 错误（轮转） | `argus.error.log.N[.gz]` | 30 天 | 同上 |
| 访问（轮转） | `argus.access.log.N[.gz]` | 14 天 | 访问量大 |
| 审计（轮转） | `argus.audit.log.N[.gz]` | 180 天 | 审计线索 |
| 未分类 | 其他路径 | `--days`（默认 30 天） | 回退 |

- 对于 `runtime/python/` 下的四类标准结构化日志，**清理脚本只删除超龄轮转文件**（如 `argus.log.1`、`argus.log.2.gz`），不删除当前主日志文件（`argus.log` 等）。开发会话日志和未分类日志仍按各自策略清理。
- **保留期是清理上限**，实际可用时长受 `RotatingFileHandler` 的 `maxBytes` 和 `backupCount` 约束。

---

## 日志格式

### 人类可读格式（console）

```
2025-06-01T14:30:00 [INFO] argus_py.api.app | req=req_abc123 task=t_001 op=- event=- status=- | Application started
```

字段从左到右：

| 字段 | 来源 | 说明 |
|------|------|------|
| `req` | `contextvars` | 请求链路 ID，形如 `req_<hex>` |
| `task` | `contextvars` | 任务 ID |
| `op` | `contextvars` | 操作名称（`module.ClassName.method`） |
| `event` | `extra` | 事件名 |
| `status` | `extra` | 状态（success / error / cancelled） |

缺失的上下文字段由 `defaults` 占位为 `"-"`，不会抛 `KeyError`。

### JSON 格式（app_file / error_file）

```json
{
  "timestamp":"2025-06-01T14:30:00+00:00",
  "level":"INFO",
  "logger":"argus_py.api.app",
  "message":"Application started",
  "module":"app",
  "function":"create_app",
  "line":42,
  "requestId":"req_abc123",
  "extra":{"customField":"value"}
}
```

JSON 输出由 `JsonLogFormatter` 生成（`argus_py.observability.logger`），
所有字段经过递归脱敏。

---

## 上下文字段注入

`ContextLogFilter` 在每个日志记录上自动设置以下字段，无需调用方手动传递：

| ContextVar | 日志 Record 字段 | 设置者 |
|------------|-----------------|--------|
| `request_id` | `request_id` | `RequestLoggingMiddleware` / `new_request_id()` |
| `task_id` | `task_id` | `@log_operation(task_arg="task_id")` 或手动 `bind_context()` |
| `operation` | `operation` | `@log_operation` 自动填写 `module.ClassName.method` |
| `actor` | `actor` | 认证中间件（API Token / 后续 SSO） |

### 手动绑定上下文

```python
from argus_py.observability.context import bind_context

with bind_context(task_id="t_001", operation="custom.action"):
    logger.info("这条日志自动带上 task_id 和 operation")
```

### 跨线程传播

`bind_context` 只影响当前线程/协程。在线程池中执行时使用
`run_in_thread()` 自动捕获并传播当前上下文：

```python
from argus_py.observability.context import run_in_thread

result = await run_in_thread(sync_function, arg1, arg2)
```

---

## `audit()` — 业务审计日志

审计日志记录**用户可感知的业务操作**，同时写入日志文件和事件总线
（容器上下文）。

```python
from argus_py.observability.audit import audit

# 基本用法
audit("task.create", task_id="t_001", status="success")

# 带详细字段
audit("task.create", task_id="t_001", status="success",
      details={"project": "my-project", "goal": "..."})
```

### 审计事件命名惯例

事件名遵循 `domain.action` 格式：

```
task.create
task.start
task.cancel
task.retry
model_config.create
model_config.test
project.delete
```

### 零依赖降级

CLI / 脚本等没有 `AuditService` 注册的上下文自动降级为只写 `argus.audit`
logger，不发布事件总线。调用方无需关心运行环境。

---

## `log_event()` — 结构化事件日志

在非服务方法的代码路径（中间件、lifespan 钩子、工具函数）中直接记录
结构化事件：

```python
from argus_py.observability.events import log_event, STATUS_ERROR, STATUS_SUCCESS

logger = logging.getLogger(__name__)

log_event(logger, "lifespan.startup",
          status=STATUS_SUCCESS,
          details={"version": "0.1.0"})

log_event(logger, "db.migration",
          status=STATUS_ERROR,
          duration_ms=150.3,
          exc_info=True)
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `event` | str | 事件名，推荐 `namespace.action` |
| `status` | str | `success` / `error` / `cancelled` 或自定义 |
| `duration_ms` | float | 耗时（毫秒），可选 |
| `details` | dict | 额外结构化字段，自动脱敏 |
| `http` | dict | HTTP 相关字段 |
| `message` | str | 自定义可读消息，缺省自动生成 |
| `level` | int | 显式日志级别；缺省时 error/cancelled 用 WARNING，其余用 INFO |
| `exc_info` | bool | 是否附带异常 traceback |

---

## `@log_operation` — 方法执行切面

在 Service 层方法上添加装饰器，自动记录执行耗时、结果状态和上下文：

```python
from argus_py.observability.aspect import log_operation

class TaskLifecycleService:

    @log_operation("task.create", task_arg="task_id")
    async def create_task(self, task_id: str, goal: str) -> Task:
        ...
```

### 参数

| 参数 | 说明 |
|------|------|
| `event` | 事件名，写入 `extra.event` |
| `task_arg` | 函数参数名，自动从中提取 `task_id` 注入上下文 |
| `include_args` | 是否将函数参数记录到 `extra.details.args`（默认 false） |
| `logger_name` | 日志记录器名，默认 `argus.operation` |

### 输出示例（JSON）

```json
{
  "event": "task.create",
  "status": "success",
  "operation": "argus_py.task.lifecycle.TaskLifecycleService.create_task",
  "taskId": "t_001",
  "durationMs": 12.34
}
```

### 适用位置

- Service 层的公共方法（CRUD、状态流转）
- 有明确开始/结束边界的操作

不适合在中间件、事件回调、短工具函数中使用（应直接用 `log_event`）。

---

## CLI 输出分层

CLI 命令有两套独立的输出渠道，彼此不冲突：

### 用户面向输出（`cli_` 系列）

```python
from argus_py.cli.io import cli_print, cli_success, cli_warn, cli_error

cli_print("开始执行任务...")
cli_success("任务完成")
cli_warn("发现 3 个问题")
cli_error("任务失败", detail="超时", hint="增加 --timeout 后再试")
```

- `cli_print` / `cli_success` / `cli_info` → stdout
- `cli_warn` / `cli_error` / `cli_cancelled` → stderr
- 不经过 Python logging 模块，不受日志级别影响

### 调试日志（`setup_cli_logging`）

```python
from argus_py.cli.io import setup_cli_logging

# --verbose=0 → WARNING, --verbose=1 → INFO, --verbose>=2 → DEBUG
setup_cli_logging(verbose=args.verbose)
```

- 只在 stderr 输出，不写文件（不与其他进程争抢 `argus.log`）
- 默认 WARNING，`--verbose` 降低到 INFO/DEBUG
- 第三方库保持 WARNING

### 任务结果输出

```python
from argus_py.cli.io import print_task_result

print_task_result(task, show_steps=True)
# 输出：
#   任务 ID：t_001
#   任务状态：completed
#   执行步骤：5
#   问题数量：2
#   结果摘要：登录成功
#   HTML 报告：outputs/reports/t_001/index.html
```

---

## 敏感数据脱敏

所有经过 `JsonLogFormatter` 的日志字段都会被递归脱敏。脱敏规则
定义在 `argus_py.redaction` 模块：

- `key=value` 形式的敏感键值：`api_key=sk-xxx` → `api_key=[REDACTED]`
- HTTP Authorization 头部：`Authorization: Bearer eyJ...` → `Authorization: Bearer [REDACTED]`
- JSON 中的敏感字段：`"token": "abc"` → `"token":"[REDACTED]"`

不经过 JSON formatter 的日志（console handler 的文本格式）不会自动
脱敏，因此不要在文本日志中打印 API Key 等敏感信息。

---

## 第三方库降噪

`config/logging.yaml` 中已配置以下第三方库的日志级别：

| Logger | 级别 | 原因 |
|--------|------|------|
| `uvicorn.access` | WARNING | 与 `RequestLoggingMiddleware` 重复 |
| `uvicorn.error` | INFO | |
| `httpx` | WARNING | 避免透传 HTTP 请求/响应细节 |
| `httpcore` | WARNING | |
| `asyncio` | WARNING | |
| `watchfiles` | WARNING | |

---

## 修改 `config/logging.yaml` 的原则

1. **不新增顶层 logger 名称** — 先确认现有命名空间能否满足
2. **新增 handler 必须配对清理** — 新增文件 handler 时同步在
   `scripts/cleanup_outputs.py` 中添加清理规则
3. **不降低第三方库的降噪级别** — 除非正在调试该库的行为
4. **修改后验证** — 启动 server 确认日志文件正确分割、无 `KeyError`
