# Argus 优化审计与实施记录（2026-09-02）

> 本批次在 O-01～O-11 与 08-25/08-27 收尾之后，推进**诊断中心二期闭环**与
> **回归批次性能热点**；不解除单进程/单副本硬约束。

## 已完成

### A. 跨服务链路底座

1. **进程 `runId` + 日志字段**
   - `observability/context.py`：`init_process_run_id` / `get_process_run_id`（`ARGUS_RUN_ID` 可注入）。
   - `JsonLogFormatter` 白名单输出 `runId`，并固定 `service=argus-python` / `component=python`。
   - lifespan 启动时初始化 runId，写入系统事件 `service.started` / `service.stopped`。

2. **Python→Java `X-Request-ID`**
   - `WhiteboxClient._request` 从 context 注入头；调用方显式头不覆盖；无 request 时用 task 派生或新生成。

3. **Java Filter + JSONL**
   - `RequestIdFilter`：读/生成 `X-Request-ID`，MDC `requestId`，响应回写。
   - `logback-spring.xml`：控制台可读 + `runtime/java/argus-java.jsonl`（路径 `ARGUS_JAVA_LOG_DIR`）。
   - 单测 `RequestIdFilterTest`（**未执行 Maven，由用户验证**）。

4. **诊断 store 识别 runtime java/web/system**
   - 扫描 `runtime/{python,java,web,system}`；Java 无 runtime 时仍回退 dev 会话。
   - 组件推断与 `search_by_request_id` 跨端时间序单测。

### B. 前端异常 / 系统信息 / 系统事件 / 概览

- `POST /diagnostics/frontend-events` → `runtime/web/frontend-events.jsonl`（有界、脱敏）。
- `GET /diagnostics/system`、`/events`、`/overview`。
- 前端：`main.ts` 上报（短窗去重）；诊断页新增概览/系统事件/系统信息 Tab；横幅改为链路已接通说明。
- `cleanup_outputs.py`：java 30 天、frontend-events 14 天、system-events 90 天；保留目录节点。

### D. 回归批次性能

- `create_run`：单次 `run_in_thread` 批量创建子任务 + `attach_tasks`，再在 loop 上 `try_enqueue`。
- queue-full abort / `cancel_run`：批次项状态批量 `update_item_statuses`，减少 N 次 SQLite 往返。
- 队列 cancel / lifecycle cancel 仍逐任务（异步队列与令牌 API 限制）。

## 明确未做

- 诊断导出 / 诊断包 API。
- Loki/OpenSearch、异常聚类、OpenTelemetry。
- 多 worker / 外置队列。

## 验证

- 计划执行：`ruff` / `mypy` / `pytest unit+integration`、前端 `eslint` / `vue-tsc` / `vitest`、`pnpm codegen:check`。
- **Java：未执行 Maven 编译/测试，由用户自行验证**（建议 `mvn test` + 本地 analyze 确认 JSONL 与 Request ID）。

## 兼容 / 迁移

- 仅新增日志字段与 API；无 DB 迁移。
- 旧 Java 无 Filter 时追踪页仍可只有 Python 段。
- OpenAPI 变更后需重新 codegen 前端类型。
