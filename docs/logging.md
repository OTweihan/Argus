# 后端日志约定

Argus 后端日志由 `argus_py/observability/` 模块统一管理，覆盖结构化输出、上下文链路、脱敏、审计与请求中间件。本文档汇总日志相关的约定与扩展方式。

## 配置文件总览

| 配置 | 路径 | 作用 |
| --- | --- | --- |
| 日志配置 | [config/logging.yaml](../config/logging.yaml) | Formatter / Filter / Handler / Logger 拓扑 |
| 服务配置 | [config/server.yaml](../config/server.yaml) | `observability.*` 开关：`request_logging` / `operation_logging` / `audit_logging` / `llm_trace` |
| 服务参数 | [argus_py/config/server_settings.py](../argus_py/config/server_settings.py) | YAML 到强类型字段的映射 |
| LLM trace 环境变量 | `.env` / 进程环境 | `LLM_TRACE_ENABLED` / `LLM_TRACE_MAX_SIZE_MB` / `LLM_TRACE_CONTENT_REDACT` 可覆盖 YAML |

## Logger 命名约定

- **业务模块** 一律使用 `logging.getLogger(__name__)`，得到形如 `argus_py.task.lifecycle` 的层级名，自动挂在 `argus_py` logger 下，享受 DEBUG 级别和文件输出。
- **专有命名空间**（不要用 `__name__`，要显式命名）：

  | logger 名 | 用途 | 输出文件 |
  | --- | --- | --- |
  | `argus.request` | HTTP 访问日志（由 [RequestLoggingMiddleware](../argus_py/observability/middleware.py) 写） | `outputs/logs/argus.access.log` |
  | `argus.operation` | `@log_operation` 装饰器产生的方法 trace | `outputs/logs/argus.log` |
  | `argus.audit` | 用户感知动作审计（由 `audit()` 写） | `outputs/logs/argus.audit.log` |

- **不要** 写 `logging.getLogger("argus")` 之外的自定义短名字，会跳过 `argus_py` / `argus` 两个根节点。

## Handler 与文件分离

[config/logging.yaml](../config/logging.yaml) 默认拆分以下输出：

- `console` — 人类可读，包含 `req=... task=... op=... event=... status=...` 链路字段。
- `app_file` — 主业务日志，JSON，按 10MB 滚动（5 份历史），路径 `outputs/logs/argus.log`。
- `error_file` — 仅 `ERROR` / `CRITICAL`，方便单独排查或告警。
- `audit_file` — `argus.audit` 专用，独立轮转（保留 10 份）。
- `access_file` — `argus.request` 专用。

> Worker 当前是同进程 asyncio，`RotatingFileHandler` 安全。若未来拆出独立进程，需要换 `QueueHandler` 或 `WatchedFileHandler`。

## 何时用哪一种日志 API

| 场景 | 推荐 API | 说明 |
| --- | --- | --- |
| 服务方法执行 trace（耗时、成功/失败、调用栈） | `@log_operation("ns.action", task_arg="task")` | 自动绑定 `task_id` / `operation` 链路字段，受 `observability.operation_logging` 控制 |
| 任何"有结构的事件" | `log_event(logger, event, status=..., duration_ms=..., details=...)` | 帮你写好 `extra` payload，复用 `JsonLogFormatter` 的脱敏 |
| 用户感知的业务动作（CRUD、登录态变更、任务取消等） | `audit("namespace.action", task_id=..., **details)` | 写入 `argus.audit` 专用文件，CLI 与 server 均可调用，零运行时依赖 |
| HTTP 请求 | 已由 [RequestLoggingMiddleware](../argus_py/observability/middleware.py) 自动处理 | 通过 `quiet_paths` / `quiet_prefixes` 静音健康检查与静态资源 |
| LLM 调用 trace | [argus_py/observability/llm_trace.py](../argus_py/observability/llm_trace.py) 的 `write_trace(record)` | 按 `task_id` 写 jsonl，受 `llm_trace.*` 配置控制 |
| 普通日志（调试、警告） | `logger.info/warning/exception("msg %s", arg, extra={...})` | extra 字段不在白名单时会归集到 JSON 的 `extra` 子对象 |

## 上下文字段

[argus_py/observability/context.py](../argus_py/observability/context.py) 暴露 `bind_context(...)`：

```python
from argus_py.observability import bind_context

with bind_context(request_id="req_xxx", task_id="t_123", operation="custom.flow"):
    do_work()
```

支持字段：`request_id` / `task_id` / `operation` / `actor`。`ContextLogFilter` 会自动把它们注入 `LogRecord`，被 console 的 `human` formatter 和 `JsonLogFormatter` 一并输出。

HTTP 请求由中间件自动绑定 `request_id` / `operation="http.request"`；任务执行入口由 `@log_operation(task_arg=...)` 自动绑定 `task_id` / `operation`。

## 脱敏规则

[argus_py/observability/redaction.py](../argus_py/observability/redaction.py) 的 `redact()` 会递归处理 `JsonLogFormatter` / `audit()` / `log_operation` 中的 payload：

- Key 命中 `api_key` / `apikey` / `authorization` / `cookie` / `password` / `secret` / `token`（含 `-`/`_` 容错）→ 值替换为 `***`。
- 字符串值若是 URL，query 中的同名参数也会被脱敏。
- LLM trace 还启用 [llm_trace.py](../argus_py/observability/llm_trace.py) 的内容级正则脱敏，匹配 `sk-...` / JWT / URL 内嵌凭据 / `key=value` 形式的内联敏感字符串。

新加敏感字段时，把 key 加入 `SENSITIVE_KEYS`（或 `_SENSITIVE_KEYS`），无需改下游代码。

## CLI 输出与日志的分层

- 用户面信息（命令结果、提示）必须用 [argus_py/cli/io.py](../argus_py/cli/io.py) 中的 `cli_print` / `cli_success` / `cli_info` / `cli_warn` / `cli_error` / `cli_cancelled`，**不要** 直接 `print()`。
- CLI 一次性命令在 `main()` 入口调用 `setup_cli_logging(verbose=...)`，只往 stderr 写人类可读 logger 输出，不写 `outputs/logs/argus.log`，避免与 `argus serve` 进程争抢文件。
- 默认级别为 `WARNING`；`-v` → INFO，`-vv` → DEBUG。
- `serve` 命令交给 FastAPI lifespan 走 `setup_logging()`，加载完整 YAML 配置。

## 配置开关一览

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `observability.request_logging` | `true` | 是否注册 `RequestLoggingMiddleware` |
| `observability.operation_logging` | `true` | `@log_operation` 是否实际写日志（关掉只跳过日志，仍维持 contextvars 绑定）|
| `observability.audit_logging` | `true` | 是否把审计动作发布到事件总线（不影响 `audit()` 写日志，关掉只静默 WebSocket 推送）|
| `observability.llm_trace.enabled` | `true` | 是否落盘 LLM trace |
| `observability.llm_trace.max_size_mb` | `50` | 单 task 的 trace 文件大小上限 |
| `observability.llm_trace.content_redact` | `true` | 是否对 LLM trace 启用内容级脱敏 |

环境变量 `LLM_TRACE_ENABLED` / `LLM_TRACE_MAX_SIZE_MB` / `LLM_TRACE_CONTENT_REDACT` 可覆盖 YAML。

## 扩展指引

- 想新增结构化字段：用 `logger.info("msg", extra={"foo": "bar"})`，`JsonLogFormatter` 会把不在白名单的 `extra` 自动放进 JSON 的 `extra` 子对象。
- 想新增审计点：直接调用 `audit("namespace.action", task_id=..., **details)`，无需注入任何依赖。
- 想暂时把某个第三方库刷屏抑住：在 [config/logging.yaml](../config/logging.yaml) 的 `loggers:` 中加 `level: WARNING` 一项即可。
- 想在测试里 reset `@log_operation` 的开关缓存：调 `argus_py.observability.aspect.reset_operation_logging_cache()`。
