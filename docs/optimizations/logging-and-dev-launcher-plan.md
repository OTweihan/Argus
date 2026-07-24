# 日志归档与一键启动统一方案

## 1. 决策

不将所有日志简单合并到一键启动器的 `combined.log`，也不继续保留彼此同义、无法区分用途的多份
日志。日志按“开发会话输出”和“运行时结构化记录”分层保存：前者由 `node scripts/dev.mjs` 统一
托管，后者由服务自身按结构化语义写入。历史日志属于测试数据，可在目录迁移时直接清理，不要求
兼容或搬迁。

一键启动器目前已经将 Python、Vite 和 Java 的 stdout/stderr 同时写入会话级 `combined.log` 与各服务
独立文件；Python 同时写 `argus.log`、错误、审计和访问日志。这不是应消除的重复：前者用于复现一次
本地开发启动与跨服务故障，后者用于按请求、任务、审计事件和错误进行机器检索。

## 2. 目标目录与责任

```text
outputs/logs/
├── dev/<run-id>/
│   ├── combined.log          # 一次 dev.mjs 启动的时间序列总览
│   ├── python.log            # Python 进程 stdout/stderr
│   ├── frontend.log          # Vite 进程 stdout/stderr
│   └── java.log              # Java Analyzer 进程 stdout/stderr
└── runtime/python/
    ├── argus.log             # DEBUG-WARNING 结构化业务日志
    ├── argus.error.log       # ERROR/CRITICAL 结构化日志
    ├── argus.audit.log       # 用户可感知操作的审计日志
    └── argus.access.log      # HTTP 访问日志
```

- `dev/<run-id>/` 是开发会话证据。启动器是唯一写入者，负责创建目录、给每行追加时间、服务名和
  stdout/stderr 通道；不要求应用修改 logging 配置以配合它。
- `runtime/python/` 是 Python 服务的结构化运行记录。保留 JSON 格式、上下文字段、脱敏和现有
  handler 路由；不把 Java/Vite 的文本输出伪装成 Python JSON 日志。
- Java Analyzer 在开发态由 `dev/<run-id>/java.log` 收集，在容器/生产态写 stdout 并由部署平台采集；
  Vite 同理，仅属于开发会话日志。首期不为二者额外复制一套本地文件 handler。
- CLI 一次性命令继续仅输出 stderr 调试日志，不争抢运行时文件 handler；其面向用户的输出保持
  stdout/stderr 分流。

## 3. 清理与保留规则

目录调整随实现一次完成；旧 `outputs/logs/argus*.log` 可删除，不迁移内容。清理脚本改为按类别使用
固定策略，而不是对整个 `logs` 目录使用同一个天数：

| 类别 | 默认保留 | 原因 |
| --- | ---: | --- |
| `dev/<run-id>/` | 14 天 | 本地调试会话可快速重现，价值随时间快速下降。 |
| `runtime/python/argus.log`、`argus.error.log` | 30 天 | 支持近期运行故障排查。 |
| `runtime/python/argus.access.log` | 14 天 | 访问量大，主要用于短期定位。 |
| `runtime/python/argus.audit.log` | 180 天 | 保留用户可感知操作的审计线索。 |

保留现有 `RotatingFileHandler` 的大小轮转作为单文件上限；时间清理由 `scripts/cleanup_outputs.py`
统一执行。清理前必须支持 `--dry-run`，且不清理 `outputs/data`、`outputs/backups`、当前仍打开的开发
会话目录或尚未达到保留期的文件。

## 4. 实施约束与验收

- `config/logging.yaml`、`argus_py/core/paths.py`、日志文档和清理脚本在同一变更中更新，避免文档指向
  旧目录。
- 一键启动器只负责子进程流的归档和终端显示，不解析、重写或脱敏应用结构化 JSON；敏感字段仍由
  Python `JsonLogFormatter` 处理。应用文本日志不得打印密钥、Token、Cookie 或认证头。
- 启动一次开发环境后，应能在同一 `<run-id>` 目录找到三项服务输出与合并时间线；Python 的每条可
  结构化检索业务/审计/访问记录仍能落入对应运行时文件，且不会出现重复 handler 写入。
- 清理 dry-run 和实际清理应分别验证四类保留期；异常退出时启动器仍关闭所有日志流，避免文件句柄残留。
