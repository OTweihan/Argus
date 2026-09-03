# Argus 优化实施记录（2026-09-03）

> 承接 09-02 审计结论中的 P1 工程项；不解除单进程/单副本硬约束，不做 export/bundles/MCP。

## 已完成

### 1. 回归 cancel / abort 批量回收

- `TaskQueue.cancel_many`：一次持锁批量移出排队任务。
- `RegressionApplicationService._reclaim_submitted_tasks`：
  - 一次 `snapshot_statuses` + `cancel_many`；
  - 一次 `load_task_headers` 判断是否已终态；
  - 仅对未终态任务 `cancel_task`（仍须逐任务落盘/发事件）。
- `leave_running_tasks=True`：创建 fail-fast 保留 running 子任务跑完；
  `False`：用户 `cancel_run` 对 running 先打取消令牌再 `cancel_task`。

### 2. 诊断 `logs_usage` TTL 缓存

- `DiagnosticsService.logs_usage`：30s TTL 缓存树扫描结果；
  每次读取仍刷新 `freeBytes`（廉价 syscall）。
- 降低 ServicesPanel 10s 刷新与 overview 的重复 `rglob` 成本。

### 3. 诊断前端请求守卫

- `ServicesPanel`：`AbortController` + 请求代次；`setInterval` 改为串行 `setTimeout`。
- `EventsPanel`：代次 + loadMore 在途防重入。
- `LogsPanel`：列表/详情/上下文均 abort + 代次；卸载取消在途请求。

### 4. correlation override 操作者

- `get_actor()` 暴露 ContextVar。
- HTTP 中间件默认 `bind_context(actor="api")`（无统一 SSO 时的最小审计主体）。
- `bind_analysis` 在 override 时写入 `source_mismatch_override_by`。

## 明确未做

- 诊断导出 / 诊断包 API、Loki、异常聚类、OpenTelemetry。
- MCP 服务、多 worker / 外置队列。
- 回归详情 WS 推送替代轮询（现有轮询已正确）。

## 验证

- 计划：`ruff` / `mypy` / 定向 pytest、前端 eslint / vue-tsc / vitest（诊断相关）。
- **未执行 Maven。**

## 兼容 / 迁移

- 无 DB 迁移、无 OpenAPI 契约变更。
- actor 默认值为 `"api"`，仅影响新 override 审计字段；旧行为未覆盖时仍为 null。
