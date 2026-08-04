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

以下次要项不强制，列为后续待办：

1. **协议白名单不一致（防御性）**：`argus_py/whitebox/config.py::validate_git_url` 只放行 `{https, http, ssh}`（+scp），而 `source_resolver.py::_ALLOWED_SCHEMES` 额外允许 `git://`。入口已拦截，属防御性不一致，统一即可。
2. **前端配置视图读取键死分支**：`argus_py/api/schemas/tasks.py::_build_whitebox_config_view` 读 `data.get("repo_url")`，但 `to_persisted()` 实际写入 `clone_url`，该 fallback 恒为 None（行为正确，编辑回填走 `task.source_repo_url`）。
3. **时间线事件缺分支**：`whitebox_source_resolved` 事件 data 未含 `requested_ref`（分支只在 `task.source_requested_ref` 持久化）。
4. **取消检查粒度**：取消 token 只在 `_poll` 每轮循环顶部检查，生效最多滞后一个 poll_interval（5–10s），可接受。
5. **`origin="remote"` 取消分支为防御代码**：Java 状态机暂不产出 CANCELLED，该分支为未来协议预留。
6. **`eligible_source_files` 为占位**：`_build_projection_data` 用 `total_source_files` 等价，待 Java 新增 `eligibleSourceFiles` 字段。
7. **端点/调用节点 `source_*` 投影列恒为 None**：Java `EndpointInfo`/`CallGraphNode` 未返回源码位置，`analysis_endpoints`/`analysis_call_nodes` 的 `source_*` 列与 API `sourceLocation` 恒为空（保留无害，0002 迁移 FORWARD-ONLY 不可 DROP）。

