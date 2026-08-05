# Argus 后续优化待办清单

_由代码审查生成的 8 项延后/待处理事项，按优先级排列。_

---

## 高优先级（代码质量/安全影响大）

### 1. `whitebox/models.py` 反序列化样板去重 ✅ 已完成

- **文件：** `argus_py/whitebox/models.py`
- **完成于：** `c212a3a`（泛型 `from_dict` 消除 ~200 行反序列化样板）、`6bdefdc`（19 个测试覆盖 17 个边界场景）

### 2. `TaskQueryService` 门面进一步扁平化 ✅ 已完成

- **文件：** `argus_py/task/query.py`（已删除）、`argus_py/runtime/container.py`、`argus_py/api/dependencies.py`
- **完成于：** `211c5db`（删除 115 行纯委托门面，health.py 直接使用 TaskReadService）、`39485c6`（测试栈清理）

### 3. `MavenClasspathResolver.java` 拆分（969 行） ✅ 已完成

- **文件：** `java_analyzer/src/main/java/com/argus/analyzer/env/MavenClasspathResolver.java`
- **完成于：** `a6a9924`（拆分）、`cd5723f`（文档）
- **拆分结果：** 10 个文件，最大 312 行，门面仅 47 行

---

## 中优先级（代码一致性/可维护性）

### 4. Java DTO 转 record（Java 21） ✅ 已完成

- **文件：**
  - `java_analyzer/.../api/dto/AnalyzerDiagnostics.java`（157 行，纯 getter/setter）
  - `java_analyzer/.../env/ClasspathResult.java`（108 行，9 参数构造器 + 位置布尔标志）
- **完成于：** `163b8fd`

### 5. `run_in_thread` vs `asyncio.to_thread` 统一 ✅ 已完成

- **影响文件：** 约 7 个使用 `asyncio.to_thread` 的文件 vs. 13 个使用 `run_in_thread` 的文件
- **完成于：** `93a5df2`

---

## 低优先级（代码整洁/锦上添花）

### 6. `auth.py._reject()` 用 `error_response()` 替代手动 ASGI 构造 ✅ 已完成

- **文件：** `argus_py/api/auth.py:115-136`
- **完成于：** `91beab5`
- **方案：** `_reject()` 签名从 `(scope_type, send)` 扩展为 `(scope, receive, send)`，HTTP 分支委托给 `error_response()` → `JSONResponse.__call__()`，删除手动 ASGI 构造及 `json`/`jsonable_encoder` 导入。WebSocket 拒绝保留直接 `websocket.close`

### 7. 前端全局错误处理器提取共享 helper ✅ 已完成

- **文件：** `frontend/src/main.ts:18-50`
- **完成于：** `007e9ee`
- **方案：** 提取 `reportGlobalError(consolePrefix, title, message, error?)` 模块级 helper + `ERROR_NOTIFICATION_DURATION` 常量，三个全局处理器各简化为一行调用。helper 保留在 `main.ts` 以避免给 `utils.ts` 引入 Element Plus 依赖

### 8. `ExecutionFlowTracer` DFS 修复补充回归测试 ✅ 已完成

- **文件：** `java_analyzer/src/test/java/com/argus/analyzer/service/ExecutionFlowTracerTest.java`
- **完成内容：** `shouldTraceSharedNodeAcrossBranches` 覆盖共享节点重新进入、下游节点不丢失且输出不重复。

### 9. `MavenExecutor` 异常体系接入 — `fail()` → 类型化异常 ✅ 已完成

- **文件：**
  - `java_analyzer/.../env/classpath/maven/MavenExecutor.java`（当前仍用 `fail()` → `ClasspathResult` 模式）
  - `java_analyzer/.../env/classpath/gateway/MavenClasspathGateway.java`（需新增 catch 层）
- **完成内容：** Executor 抛出类型化异常，Gateway 统一转换回 `ClasspathResult`，并保留命令、耗时、stdout/stderr 尾部和 timeout 诊断。
- **方案：**
  1. `MavenExecutor` 中 `executeMaven()` 改为抛 `ClasspathException` 子类：
     - timeout → `MavenTimeoutException`
     - exit ≠ 0 → `MavenExecutionException`
     - 文件未生成 → `ClasspathGenerationException`
     - IOException → `ClasspathGenerationException`
  2. `MavenClasspathGateway` 捕获类型化异常并转为 `ClasspathResult`（保持上层 Resolver 对异常的零感知）
  3. 删除 `MavenExecutor.fail()` 3 个重载
- **收益：**
  - 上层可通过 `catch (MavenTimeoutException)` / `catch (MavenExecutionException)` 做差异化处理
  - `MavenExecutionException.outputTail` 让上层无需查日志即可排查
  - 替代字符串判断的脆弱模式
- **风险：** 低 — 行为不变（异常 → ClasspathResult 转换在 Gateway 层），纯内部重构

### 10. 全仓可靠性与安全优化 ✅ 已完成

- Java 分析缓存升级为请求键 + 源码内容指纹、single-flight、有界 LRU。
- Java 异步作业和内部分析使用独立有界执行器，作业结果具备容量与 TTL 回收。
- Python 补齐 Whitebox HTTP 客户端、SQLite 连接池、IO executor 与 Worker 停机生命周期。
- 限流示例对齐真实 `/argus/api` 路径，Token 桶增加机会式清理。
- Web 控制台支持 sessionStorage Token、Bearer API、鉴权 WebSocket 与 Blob 资源加载。
- CI 对齐 `master` 分支并将 Playwright smoke 恢复为阻断项。

---

## 已完成的总结

本次共完成 **21 项**优化：

| 维度 | 数量 | 示例 |
|------|------|------|
| Bug 修复 | 2 | DFS visited 跨分支污染、URL 正则过宽 |
| 死代码删除 | 7 | TaskService(328行)、docker-compose.core.yml、空文件/空导入 |
| 去重简化 | 7 | 错误响应统一、CLI 签名统一、TaskApplicationService 工厂、auth._reject() ASGI 去重、前端全局错误 helper |
| 配置卫生 | 4 | uv 版本统一、.gitignore 补充、CI 路径过滤、argparse 迁移 |
| Java 加固 | 2 | CallGraphBuilder 异常收窄、SourceScannerCache 提取 |
| 审查修复 | 4 | SubParserAdder 提取到 `_types.py`、方法→独立函数、json import 提升、type=Path |

**净减少代码：** ~433 行（删除约 663 行，新增约 230 行）

---

## 白盒/黑白盒关联计划收尾审计 — 遗留次要待办（2026-08-04）

整体审计 `docs/optimizations/whitebox-and-blackbox-correlation-plan.md`：阶段三、四已完成；阶段一、二经本批次修复补齐实质缺口（git 源快照标识、失败错误码持久化、报告侧 completeness/降级横幅、`sourceLocation` Python 侧收敛、`cancel_job` 死代码清理、`analysis_repo._row_to_analysis_run` 的 sqlite3.Row `.get()` 崩溃修复）。

以下次要项不强制，已于 2026-08-05 全部处理完毕（代码改动或复核确认）：

1. **协议白名单不一致（防御性）** ✅ 已处理：`source_resolver.py::_ALLOWED_SCHEMES` 移除 `git://`，与 `config.py::validate_git_url` 入口白名单统一为 `frozenset({https, http, ssh})`；解析器报错消息改为按排序确定性输出。
2. **前端配置视图读取键死分支** ✅ 已处理：`_build_whitebox_config_view` 兜底键 `data.get("repo_url")` 改为 `data.get("clone_url")`（与 `to_persisted()` 实际写入键一致），主路径仍走 `task.source_repo_url`。新增 `tests/unit/test_tasks_config_view.py` 覆盖主路径与兜底路径。
3. **时间线事件缺分支** ✅ 已处理：`whitebox_source_resolved` 事件 data 补充 `requested_ref`，时间线可还原用户请求的 ref；新增集成测试断言事件携带分支。
4. **取消检查粒度** ✅ 已复核，维持现状：取消 token 在 `_poll` 每轮循环顶部检查，滞后最多一个 poll_interval（5–10s），且 transient error 退避、`get_analyze_job` 请求时间均受 deadline 与 request_timeout 约束，可接受，不引入更细粒度检查。
5. **`origin="remote"` 取消分支为防御代码** ✅ 已复核，维持现状：Java 状态机暂不产出 CANCELLED，该分支为未来协议预留；接线已由 `test_job_cancelled_remote` 覆盖（远端确认取消 → `CANCELLED` 终态）。
6. **`eligible_source_files` 为占位** ✅ 已复核，维持现状：已确认 Java `AnalyzerDiagnostics` 仅含 `totalSourceFiles`，无 `eligibleSourceFiles` 字段；`_build_projection_data` 中占位注释保留，待 Java 端新增字段后再区分。
7. **端点/调用节点 `source_*` 投影列恒为 None** ✅ 已处理（决策保留列 + 一致性收尾）：Java `EndpointInfo`/`CallGraphNode` 未返回源码位置，`source_*` 列保留无害（0002 迁移 FORWARD-ONLY 不可 DROP）；`call_nodes` 的 `source_file` 由 `""` 规范化为 `None` 与端点列一致（API 层两种取值均返回 `sourceLocation=null`），并补充保留语义注释。

---

## 白盒/黑白盒关联计划整体复核 — 新增次要待办（2026-08-05）

对 `docs/optimizations/whitebox-and-blackbox-correlation-plan.md` 四阶段整体复核确认：阶段一、二、三、四均已落地。
本次修复 1 个实质接线缺口：**本地取消时 analysis_runs 由 FAILED 改为落 `STOPPED_WAITING` 终态**（远端确认取消 → `CANCELLED`，任务超时 → `TIMED_OUT`），
新增 `analysis_repo.mark_terminal` / `storage.mark_analysis_terminal` / `lifecycle.mark_analysis_terminal` 三层透传，
与 `AnalysisRunStatus` 枚举、前端「已停止等待/已取消/超时」展示对齐；时间线事件与失败消息保留不变，任务级状态仍由 `execution/runner.py` 映射为 CANCELLED/TIMEOUT。

以下为本次复核新发现次要项，不强制，已于 2026-08-05 全部处理完毕（代码改动或复核确认）：

1. **`EndpointEvidence.match_reason_code` 死字段** ✅ 已处理（连同孪生死字段 `EndpointEvidenceCandidate.reason_code` 一并清理）：两字段恒 `""`、无任何消费方（前端表格/详情均不渲染）。从 dataclass、`_ee_to_row`/`insert_evidence_batch`/`insert_candidates_batch` 写入、`EndpointEvidenceResponse`/`EndpointEvidenceCandidateResponse` API schema 全部移除；同步删除前端 `EndpointEvidenceInfo.matchReasonCode`、`EndpointEvidenceCandidateInfo.reasonCode` 类型与测试 fixture，并重新生成 `openapi.gen.ts`（`pnpm codegen:openapi`）。DB 列保留（0004 迁移 FORWARD-ONLY 不可 DROP，默认值兜底）。
2. **`correlation_repo.get_summary` 的 `candidate_related_finding_count` 恒为 0** ✅ 已处理：三桶改为按请求证据切分并保证 `confirmed + candidate + unrelated == total`——`confirmed` = `confirmed_request_count > 0`（黑盒实际触达）、`candidate` = 静态关联但无触达请求（`confirmed_request_count == 0 AND candidate_request_count > 0`）、`unrelated` = 其余。报告聚合 `_accumulate_correlation_sums` 同步纳入 `candidateRelatedFindingCount`。**口径说明**：`confirmed` 语义从「按 relation 类型」收紧为「按请求证据」——未触达的 DIRECT_HANDLER finding 现在落入 candidate。此举同时消除了既有双口径不一致：此前 summary 的 confirmed 按 relation 类型统计，而前端 `FindingEvidenceTable` 的 `confirmedCount`/`candidateCount` 一直按 `confirmedRequestCount`/`candidateRequestCount > 0` 统计，两处数字本就不可比；新实现使 summary 与表格同口径（confirmed 均 = 触达请求数 > 0）。CorrelationTab 顶部分类计数与表格明细因此语义一致。
3. **`PathMapping`（网关前缀剥离）休眠** ✅ 已处理（完整接线）：新增 `ServerSettings.correlation_gateway_strip_prefixes` / `correlation_gateway_prepend_prefix`（含 `config/server.yaml` 示例），容器经 `_build_path_mapping_from_settings` 构造 `PathMapping` 注入 `EndpointMatcher(path_mapping=...)`（容器异步路径 + `application._execute_matching_sync` 同步路径）；`_match_single` 在匹配前按段边界剥离/重挂前缀，命中时产出 `PATH_MAPPING_APPLIED` 诊断（激活原本休眠的枚举值）；`correlation_config_digest` 纳入前缀配置。默认空 → 行为不变。
4. **自动绑定回退放宽快照边界（设计取舍）** ✅ 已复核，维持现状：黑盒任务无快照时回退绑定「同项目最新成功分析」并标 `UNVERIFIED`，严格「同一源码快照」仅在手动绑定路径强制；`_on_whitebox_analysis_succeeded` 空快照回退同样标 `UNVERIFIED`，`source_alignment_status` 已持久化并对外展示，审计可追溯。属刻意放宽的默认行为，不收紧。
5. **`config_json` 存 `clone_url` 原始 URL** ✅ 已复核，维持现状：确认 `analysis_runs.config_json` 仅内部存储（API/报告响应均不含该字段），展示/审计走 `task.source_repo_url`（`_sanitize_repo_url_for_display` 剥离 userinfo），仅用户名 URL 的泄露面仅限库内 at-rest，风险低；编辑表单回填该值即用户自身输入，无新增暴露。
6. **CLI 终端无结构化降级徽标** ✅ 已处理：`cli/io.py::print_task_result` 新增 `_print_whitebox_degradation`，解析 `task.result_json` 的 `completeness` + `qualityIssues`（与 HTML 报告模板/前端 CompletenessBanner 同一来源），当 `DEGRADED`/`UNAVAILABLE`/`NOT_EVALUATED` 时向 stderr 打印「白盒分析降级/结果不可用/完整性未评估」标题与逐条质量问题；黑盒任务及无 `completeness` 键时静默。

