# 剩余优化审计（2026-09-08）

承接 [09-07](remaining-optimization-audit-2026-09-07.md)。本轮为 **D-01～D-06 合入后的盘点**：
确认诊断导出加固已完成，修正过期文档指针，并列出下一批可选项。
本次以静态复核与文档收敛为主，**未修改业务代码**（除非另有说明的文档 Batch）。

## 1. 范围与依据

- 工作区：`master` 与 origin 同步，无未提交业务改动（文档 Batch 除外）。
- 依据：架构基线、近期 commit、诊断 store/export/routes、历史审计系列、CodeGraph 抽查。
- 非范围：全仓性能基准、Java 算法全面审计、Maven 编译/测试。

## 2. 已完成（不再列入待办）

| 领域 | 状态 | 代表提交 / 说明 |
|------|------|-----------------|
| O-01～O-11 及 08-18/08-25/08-27/08-31 正确性与资源项 | 已完成 | 见各日审计 |
| 诊断中心 MVP + 二期 + 四期导出/诊断包 | 已完成 | 09-02 / 09-04 |
| **D-01** 超时与后台线程闸门、导出级扫描预算 | 已完成 | `ac96f00` |
| **D-03** 诊断包容量准入、定时回收、claim 下载 | 已完成 | `ac96f00` |
| **D-02 / D-06** 跨文件时间归并、精确 truncated | 已完成 | `f254e28` |
| **D-04 / D-05** manifest 真实性、分块流式 ZIP | 已完成 | `f6ff777` |
| 回归闭环首期 + cancel 批量回收 + 详情串行轮询 | 已完成 | 08-27 及后续 |

代码侧静态复核：**未发现与 09-07 同级的新 P0/P1 正确性缺陷**（非运行时复现结论）。

## 3. 本轮文档 Batch（已实施）

| 编号 | 事项 | 处理 |
|------|------|------|
| DOC-01 | `AGENTS.md` / `CLAUDE.md` 指向不存在的 `follow-up-optimizations.md` | 改为指向本目录及本文件 |
| DOC-02 | `docs/architecture.md` §13 仍链 09-04 | 更新为本文 |
| DOC-03 | 09-07 文首仍写「待实施」 | 增加已落地状态段并链到本文 |
| DOC-04 | `diagnostics-center-plan.md` 残留「仍未建设导出」 | 修正为已落地 + D 系列说明 |

## 4. 仍可优化项（按优先级）

### 4.1 P1 — MCP 只读工具面（设计已就绪，代码未落地）

- 设计：[mcp-server-design.md](mcp-server-design.md)
- 现状：`argus_py/mcp/` 不存在
- 建议 Phase 1：包骨架 + 官方 `mcp` SDK（锁 minor）+ 查询类 tools/resources + Token 鉴权 + 契约快照；默认 `mcp.enabled=false`；不写操作、不 stdio 代理
- 约束：同进程挂载 FastAPI；经 RuntimeContainer 注入既有 read service；禁止独立进程直连 DB
- 验收：关闭时零开销；开启后 initialize → tools/list → 只读 call；ruff/mypy/定向 pytest；无 OpenAPI/DB 迁移

### 4.2 P2 — 条件触发（默认不做）

| 项 | 触发条件 |
|----|----------|
| Loki/OpenSearch、异常聚类、OTel `traceId` | 多节点私有化或本地扫描证明不够 |
| Java Analyzer 8081 服务间鉴权 | 对宿主或外网暴露面扩大时 |
| 多 worker / 外置队列 / EventBus / 多副本存储 | 满足 architecture §6 六项 + 可测量单进程瓶颈 |

### 4.3 P3 — 可维护性（改动热点时顺带，不单独开批次）

- 大文件：`diagnostics_store.py`、`regression/application.py`、`diagnostics_export.py`、`whitebox/runner.py` 等
- 测试双后端：`TaskFileStorage` 仍被大量单测使用，生产为 SQLite；可逐步迁 fixture
- 回归详情仍为串行 `setTimeout` 轮询（语义正确）；WS 推送、门禁/Cron/用例并行属产品决策，非当前缺陷

## 5. 推荐顺序

1. **已完成**：文档 Batch（本文与 DOC-01～04）
2. **下一功能批次（需产品确认）**：MCP Phase 1 只读
3. **明确跳过**：§4.2，除非出现对应触发条件

## 6. 兼容 / 迁移

- 本轮仅文档：无 API、schema、DB、前端生成物变更
- 无业务兼容或数据迁移影响
- 继续保持单进程/单副本硬约束

## 7. 验证

- 目标路径存在：`docs/optimizations/remaining-optimization-audit-2026-09-08.md`
- `AGENTS.md` 与 `CLAUDE.md` 历史优化链接一致且非死链
- `architecture.md` §13、诊断方案文首与 §1.4 与 D 系列状态一致
- 未运行应用、性能测试、全量自动化测试、Maven/Gradle
