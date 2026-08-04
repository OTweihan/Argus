# 一键启动终端日志紧凑聚合方案

## 1. 背景与问题

项目统一使用 `node scripts/dev.mjs` 启动 Python API、Vite 前端和 Java Analyzer。启动器当前已经完成
日志聚合和持久化：每次开发会话都会生成一份按时间排序的 `combined.log`，同时保存
`python.log`、`frontend.log` 和 `java.log` 三份服务日志。

因此，本方案要解决的不是“日志是否聚合”，而是三路日志同时写入终端时的可读性问题：

- Python、Vite、Maven 和 Spring Boot 使用不同的时间、级别和 logger 格式，混排后视觉层级不统一。
- 启动器添加的 `[service][stdout/stderr]` 与应用自身前缀叠加，单行有效信息占比偏低。
- `stderr` 不等于错误。例如 Uvicorn 会把正常启动信息写入 stderr，不能据此标红或过滤。
- Maven 生命周期、Spring Boot 启动过程和 Vite 横幅产生大量一次性输出，容易淹没服务就绪状态与业务日志。
- Java/Python 日志自带时间戳，外层归档又添加 ISO 时间，直接照搬到终端会形成双时间戳。
- 异常堆栈被逐行添加相同前缀，跨服务穿插时不容易确认堆栈归属和边界。

本方案是 [`logging-and-dev-launcher-plan.md`](logging-and-dev-launcher-plan.md) 的补充。原方案继续负责
日志目录、归档责任和保留策略；本文只定义 `dev.mjs` 的终端展示方式，不改变应用日志体系。

## 2. 设计目标

### 2.1 成功标准

- 默认终端能够快速辨认日志来自 Python、前端还是 Java。
- 服务启动、就绪、退出、告警和异常始终可见。
- Python 与 Java 的项目业务 INFO 日志实时可见，框架例行 INFO 不占据主要视野。
- 多行异常保持完整且归属明确，不因紧凑模式丢失堆栈。
- 无法可靠分类的内容默认展示，避免静默隐藏诊断信息。
- 排查底层启动问题时，可以通过一个显式参数恢复完整三路实时输出。
- 终端展示过滤不影响 `combined.log` 和各服务日志的完整性。

### 2.2 非目标

- 不引入全屏 TUI、分栏界面或运行时按键切换。
- 不统一改造 Python、Spring Boot、Maven 和 Vite 各自的日志配置。
- 不把 Java/Vite 文本日志转换成 Python JSON 日志，也不建立新的日志采集协议。
- 不根据日志文本判断业务状态；服务状态仍以子进程生命周期和健康检查为准。
- 不在本阶段增加日志搜索、Web 日志查看器或 OpenTelemetry/ELK 对接。

## 3. 最终决策

`dev.mjs` 提供两种终端模式：

| 模式 | 启动方式 | 行为 |
| --- | --- | --- |
| 紧凑模式（默认） | `node scripts/dev.mjs` | 统一格式，展示 supervisor、项目 INFO、WARN/ERROR 和无法识别的输出，收起已知框架噪声 |
| 完整模式 | `node scripts/dev.mjs --verbose` | 显示所有非空 stdout/stderr 行，用于排查 Maven、Spring、Uvicorn 或 Vite 启动细节 |

两种模式都在终端过滤之前写入完整文件日志：

```text
outputs/logs/dev/<run-id>/
├── combined.log
├── python.log
├── frontend.log
└── java.log
```

开发会话日志继续遵守现有 14 天清理策略；本文不新增日志文件，也不调整清理规则。

## 4. 终端展示规范

### 4.1 统一格式

紧凑模式使用本地时间、固定宽度服务标签、识别出的级别和精简后的正文：

```text
17:55:46 PY    INFO  已启动（PID=31844）
17:55:46 WEB   INFO  已启动（PID=70048）
17:55:46 JAVA  INFO  已启动（PID=30408）
17:55:49 PY    INFO  argus_py.infra.recovery | 没有残留的 running 任务需要恢复
17:55:58 JAVA  INFO  com.argus.analyzer... | Analyzer started
17:55:59 JAVA  READY 服务已就绪：http://127.0.0.1:8081/actuator/health
17:56:17 WEB   INFO  vite | optimized dependencies changed, reloading
```

规则如下：

- 终端只显示本地 `HH:mm:ss`，文件日志继续使用外层 ISO 时间戳。
- 服务标签统一为 `PY`、`WEB`、`JAVA`，保持固定宽度并沿用现有服务颜色。
- 不在紧凑终端显示 `stdout`/`stderr`；通道信息仍保留在文件日志中。
- `INFO`、`WARN`、`ERROR`、`READY` 等级使用一致颜色，不能从通道名称推断等级。
- 项目 logger 可保留精简名称；框架已有的重复时间、PID、应用名等前缀在能够可靠解析时移除。
- 非 TTY、重定向或 CI 环境不输出 ANSI 控制码，但文本字段和过滤规则保持一致。

### 4.2 Supervisor 输出

以下事件始终显示，不参与应用日志过滤：

- 子进程已启动及 PID。
- 健康检查通过及访问地址。
- 启动超时、进程意外退出和进程启动失败。
- 收到 Ctrl+C、优雅停止和强制终止异常。
- 全部服务就绪后的前端与 API 地址。

Supervisor 事件使用真实状态等级，而不是伪装成子进程 stdout 日志。

### 4.3 Python 分类

紧凑模式保留：

- `argus_py.*` 与 `argus.*` logger 的 INFO 及以上日志。
- 任意 logger 的 WARNING、ERROR、CRITICAL 日志。
- CLI 面向用户的输出以及无法识别格式的普通输出。
- Python traceback、异常原因和续行上下文。

紧凑模式可收起：

- Uvicorn/WatchFiles 的正常启动、重载、连接打开和连接关闭等例行 INFO。
- 与 supervisor 健康检查结果重复的 “Application startup complete” 等状态。

不得仅因内容来自 stderr 就将其判断为 WARNING 或 ERROR。

### 4.4 Java 分类

紧凑模式保留：

- `com.argus.*` 项目 logger 的 INFO 及以上日志。
- Maven、编译器、Spring Boot 和第三方组件的 WARNING/ERROR。
- Java exception、`Caused by`、suppressed exception 和完整 stack trace。
- 无法识别为 Maven/Spring 例行输出的内容。

紧凑模式可收起：

- Maven scanning、resources、compiler、testCompile 和插件阶段横幅等普通 `[INFO]`。
- Spring Boot Banner。
- Tomcat、Actuator、DispatcherServlet 等正常启动 INFO。
- 与 supervisor 就绪事件重复的 Spring 启动完成信息。

启动期间不能长时间完全无反馈：子进程启动后先显示 supervisor 的“已启动”，最终由健康检查显示
“服务已就绪”；发生 Maven/编译错误时立即显示完整错误和后续堆栈。

### 4.5 前端分类

Vite 运行期输出相对较少，采用较保守的过滤策略。紧凑模式保留：

- 编译、依赖重新优化和 HMR 事件。
- proxy error、构建错误、警告和异常堆栈。
- 无法识别的插件输出。

紧凑模式只收起 pnpm 命令回显、Vite Banner、Local URL 等与 supervisor 状态重复的启动横幅。

### 4.6 多行事件

终端分类器需要维护每个服务、每个输出通道的最近事件状态：

- 新日志首行完成服务、等级、logger 和可见性判断。
- 缩进续行、`at ...`、`Caused by:`、`Suppressed:` 及 traceback 行继承首行可见性。
- 可见异常的所有续行都必须显示，并使用对齐缩进或竖线表示同一事件。
- 被收起的普通框架事件，其明确续行一起收起，避免出现没有首行的残缺内容。
- 无法确认是否属于续行时按新未知事件处理并显示。

文件日志仍逐行写入，不因终端分组改变现有归档格式。

## 5. 实现边界

### 5.1 数据流

子进程输出的处理顺序固定为：

```text
stdout/stderr chunk
  → UTF-8 按行缓冲
  → 去除归档中的 ANSI 控制码
  → 完整写入 combined.log 和服务日志
  → 终端事件分类
  → 根据 compact/verbose 模式渲染
```

必须先归档、后过滤。终端分类器异常时应回退为显示原始行，不能影响文件写入或子进程管理。

### 5.2 代码组织

- `dev.mjs` 继续负责参数解析、进程生命周期、健康检查和日志流接入。
- 日志解析、分类和渲染应保持为无副作用的纯函数或小型状态对象，便于使用固定样例测试。
- 服务差异通过显式的 Python/Java/Vite 分类器表达，不在主进程管理流程堆叠正则分支。
- 不增加第三方 Node.js 依赖；继续只使用 Node.js 20+ 内置能力。
- 不修改 Python `config/logging.yaml`、Java `application.yml` 或前端 Vite 配置来迁就启动器。

### 5.3 命令行兼容

`dev.mjs` 支持以下接口：

```text
node scripts/dev.mjs             # 默认紧凑模式
node scripts/dev.mjs --verbose   # 完整实时输出
node scripts/dev.mjs --check     # 仅执行环境和端口检查
node scripts/dev.mjs --help      # 显示帮助
```

- `--verbose` 只影响终端输出，不提高各应用内部日志级别。
- `--check` 不创建开发会话日志目录，行为保持不变。
- 未知参数仍应明确报错。
- 暂不支持运行时按键切换，避免接管 stdin 后影响 Windows、CI 和重定向场景。

## 6. 测试与验收

### 6.1 自动化测试

使用固定日志样例覆盖：

1. Python 项目 INFO 保留、Uvicorn 例行 INFO 收起、Uvicorn ERROR 保留。
2. Java 项目 INFO 保留、Maven 生命周期 INFO 收起、编译错误及 stack trace 完整保留。
3. Vite 启动横幅收起、HMR 信息和 proxy error 保留。
4. stdout 中的 ERROR 能正确识别，stderr 中的正常 INFO 不被误判为错误。
5. ANSI 清理、Windows `\r\n`、Unix `\n`、分块截断和流结束残留行处理正确。
6. 多行 traceback、Java `Caused by` 和 Node.js stack trace 不丢行、不串到其他服务。
7. 未知格式默认显示。
8. `--verbose` 绕过紧凑过滤并显示全部非空行。
9. 非 TTY 输出不包含颜色控制码。
10. 文件写入发生在终端过滤之前，紧凑模式下被收起的行仍存在于归档文件。

### 6.2 手工验收

- 执行 `node scripts/dev.mjs`，确认三项服务的启动与就绪状态清晰可见。
- 触发一次正常 API 请求、一次前端 HMR 和一次可恢复错误，确认日志归属明确。
- 制造一个子进程启动失败，确认错误与完整根因立即显示。
- 使用 `--verbose` 启动，确认 Maven/Spring/Uvicorn/Vite 的完整输出可以恢复。
- 对照同一会话的 `combined.log`，确认终端收起的内容仍被完整保存。
- 执行 `node --check scripts/dev.mjs` 和日志分类相关 Node 测试。
- Java 侧不需要为本展示层变更修改代码；不自动执行 Maven 编译或测试，由用户自行验证。

## 7. 风险与回退

| 风险 | 控制方式 |
| --- | --- |
| 框架版本升级导致格式变化 | 未识别内容默认显示，不使用“默认隐藏”策略 |
| 正常 stderr 被误标为错误 | 优先解析内容等级，通道只写入归档元数据 |
| 多行异常被错误分组 | 仅对明确续行模式继承状态，模糊行按新事件显示 |
| 过滤规则掩盖启动细节 | `--verbose` 一键恢复完整输出，文件日志始终完整 |
| 终端渲染异常影响启动器 | 渲染失败回退原始行，不影响归档、健康检查和进程生命周期 |

若紧凑模式在实际使用中误判较多，可将默认渲染临时回退为当前完整输出；该回退不涉及日志迁移，
也不会影响既有开发会话文件。

## 8. 实施顺序

1. 将参数模型扩展为 `verbose`，同步帮助文本。
2. 提取统一事件结构、服务分类器和终端渲染器。
3. 调整行读取流程为“完整归档后再渲染”，接入多行事件状态。
4. 补充固定样例测试并验证非 TTY 行为。
5. 更新 `scripts/README.md` 与 `docs/logging.md` 中的终端模式说明。
6. 手工完成紧凑模式、完整模式、异常退出和 Ctrl+C 验收。

本方案不改变架构基线、跨服务契约、运行时结构化日志或开发日志保留策略，可以作为独立的小步优化实施。
