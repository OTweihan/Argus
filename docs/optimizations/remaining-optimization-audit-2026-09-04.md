# 剩余优化审计（2026-09-04）

> 承接 [`remaining-optimization-audit-2026-09-03.md`](remaining-optimization-audit-2026-09-03.md)。
> 本轮落地 **Batch A：诊断中心日志导出 + 实例诊断包**；未做 MCP / Loki / OTel / 多 worker。

## 1. 本轮已完成

| 项 | 说明 |
| --- | --- |
| `POST /argus/api/diagnostics/export` | zip：`manifest.json` + `logs.ndjson`；过滤含 keyword；levels=min-level |
| `POST /argus/api/diagnostics/bundles` | 创建实例诊断包；进程内登记 + TTL；`downloadPath` 相对路径 |
| `GET /argus/api/diagnostics/bundles/{bundle_id}` | **claim** 一次性下载后删临时文件 |
| 资源隔离 | 共用 semaphore / `run_in_thread` / 扫描预算；导出超时独立 30s |
| 脱敏 | 导出消息与 exception 走 `redact_sensitive_text` |
| 临时文件 | 前缀 `argus-diag-`；构建失败 unlink；启动清理扩展 |
| 前端 | 日志「导出」对齐当前筛选（含 keyword）；概览「下载诊断包」 |
| OpenAPI | 重新 codegen `frontend/src/api/openapi.gen.ts` |
| 测试 | `tests/unit/test_diagnostics_export.py` |

实现入口：

* `argus_py/observability/diagnostics_export.py`
* `argus_py/api/routes/diagnostics.py`
* `argus_py/infra/temp_cleanup.py`（`DIAGNOSTICS_BUNDLE_TMP_PREFIX`）
* `frontend/src/api/diagnostics/index.ts`
* `frontend/src/views/diagnostics/{LogsPanel,OverviewPanel}.vue`

## 2. 仍未做（优先级示意）

1. **MCP 只读工具面**（审计/排障入口，非诊断中心阻塞项）
2. **文档指针**：`AGENTS.md` 仍可能引用缺失的 `follow-up-optimizations.md`（若仍存在，应改指本系列审计）
3. **Loki/OpenSearch / 异常聚类 / OTel traceId**（诊断方案远期）
4. **Java 8081 对外暴露时的服务间鉴权**（仅当暴露面扩大时）
5. **多 worker / 外置队列** — 架构硬约束，未测到单进程瓶颈前不做

## 3. 已知取舍 / 修订（P0~P2）

* 诊断包元数据 **不持久化**：进程重启后 `GET /bundles/{id}` 全部 404。
* 下载 **claim 一次性**：领取即注销，避免并发双下。
* 首版诊断包 **不含** 独立「全量脱敏配置摘要」文件。
* 导出/打包默认 maxEvents=2000、硬顶 5000、内容字节预算 ≈50MB；`levels` = min-level。
* `diagnostics.export_timeout_seconds` 默认 30s（与查询 5s 分离）。
* 构建失败 unlink 临时 zip；`downloadPath` 相对路径；导出支持 `keyword`。

## 4. 架构基线未变

仍遵守 [`docs/architecture.md`](../architecture.md)：单进程/单副本；诊断为同进程旁路负载；组合根在 `runtime/container.py` 注入 store/service/semaphore/registry。
