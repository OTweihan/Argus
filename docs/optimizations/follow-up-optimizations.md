# Argus 后续优化待办清单

_由代码审查生成的 8 项延后/待处理事项，按优先级排列。_

---

## 高优先级（代码质量/安全影响大）

### 1. `whitebox/models.py` 反序列化样板去重 ✅ 已完成

- **文件：** `argus_py/whitebox/models.py`
- **完成于：** `c212a3a`（泛型 `from_dict` 消除 ~200 行反序列化样板）、`6bdefdc`（19 个测试覆盖 17 个边界场景）

### 2. `TaskQueryService` 门面进一步扁平化

- **文件：** `argus_py/task/query.py`、`argus_py/runtime/container.py`、`argus_py/api/dependencies.py`
- **现状：** 已删除 328 行的 `TaskService`，但 `TaskQueryService`（~115 行）仍然是一个兼容门面——其所有方法委托给 `TaskReadService`、`TraceReadService`、`DebugBundleBuilder`，而这三者已经直接暴露在 `RuntimeContainer` 上
- **调用方：** `argus_py/api/routes/health.py:53` 调用 `get_task_query_service()`
- **方案：**
  1. 在 `health.py` 中直接使用 `TaskReadService` 的方法
  2. 移除 `TaskQueryService` 及 `container.task_query_service` 字段
- **风险：** 低 — 仅一个调用点

### 3. `MavenClasspathResolver.java` 拆分（969 行）

- **文件：** `java_analyzer/src/main/java/com/argus/analyzer/env/MavenClasspathResolver.java`
- **现状：** 单一文件承担 4 项职责：Maven 可执行文件检测（8 步链）、classpath 缓存管理、Maven 进程运行、旧版解析
- **方案（3 遍迭代）：**
  1. 提取 `MavenExecutableLocator`（~150 行）—— mvnw/mvn 查找链
  2. 提取 `ClasspathCacheManager`（~100 行）—— `.argus/` 目录、缓存哈希、过期检查
  3. 提取 `MavenProcessRunner`（~200 行）—— 进程生成、stdout/stderr 读取、超时
- **风险：** 高 — 零测试覆盖；建议先补测试再重构
- **建议推进时机：** 独立分支，充分测试

---

## 中优先级（代码一致性/可维护性）

### 4. Java DTO 转 record（Java 21）

- **文件：**
  - `java_analyzer/.../api/dto/AnalyzerDiagnostics.java`（157 行，纯 getter/setter）
  - `java_analyzer/.../env/ClasspathResult.java`（108 行，9 参数构造器 + 位置布尔标志）
- **阻碍：** `ProjectAnalyzerService.java:196-206` 有大量 `diag.setXxx()` setter 调用，不能直接转为不可变 record
- **方案：** 先确认所有 setter 调用点是否都可以改为构造时传入；如果不能，考虑使用 `@Builder` 模式或保留为可变类
- **风险：** 中 — Jackson 序列化兼容需验证

### 5. `run_in_thread` vs `asyncio.to_thread` 统一

- **影响文件：** 约 7 个使用 `asyncio.to_thread` 的文件 vs. 13 个使用 `run_in_thread` 的文件
- **现状：** `run_in_thread()` 传播上下文变量（request_id、task_id），但 `whitebox/runner.py`、`execution/runner.py` 等使用原始 `asyncio.to_thread()`，在线程内打印日志时丢失上下文
- **方案：** 逐个审计 7 个调用点，对涉及日志/请求上下文的迁移到 `run_in_thread()`
- **审计清单：**
  - `execution/runner.py:107` — `to_thread` 调用
  - `whitebox/runner.py:59-63` — `to_thread` 调用
  - `cli/commands/auth.py:63` — `to_thread` 调用
  - `api/routes/reports.py:23,56,84,91` — 4 处 `to_thread` 调用
- **风险：** 低 — 替换行为等价（`run_in_thread` 是 `to_thread` 的超集）

---

## 低优先级（代码整洁/锦上添花）

### 6. `auth.py._reject()` 用 `error_response()` 替代手动 ASGI 构造

- **文件：** `argus_py/api/auth.py:115-136`
- **现状：** `_reject()` 手动构造 ASGI `http.response.start`/`http.response.body` 消息，与 `errors.error_response()` 的功能重叠
- **阻碍：** `_reject()` 只接收 `(scope_type, send)`，缺少 `scope` 和 `receive` 来调用 `JSONResponse.__call__(scope, receive, send)`。需要改 `AuthTokenMiddleware.__call__` 传入完整的 `scope`/`receive`
- **收益：** 消除重复的 content-type/content-length 手动组装逻辑
- **风险：** 低 — 改动范围仅限于 `auth.py` 内部

### 7. 前端全局错误处理器提取共享 helper

- **文件：** `frontend/src/main.ts:18-50`
- **现状：** `window.onerror`、`unhandledrejection`、Vue `errorHandler` 三个处理器各自调用 `ElNotification.error`，参数结构高度相似（title、message、duration: 5000）
- **方案：** 提取 `showErrorNotification(title: string, message: string)` 辅助函数
- **理由：** 三个处理器对应不同语义层（脚本错误/Promise 拒绝/渲染异常），标题和消息区分是合理的；但 `ElNotification.error` 调用可消除重复

### 8. `ExecutionFlowTracer` DFS 修复补充回归测试

- **文件：** `java_analyzer/src/test/java/com/argus/analyzer/service/ExecutionFlowTracerTest.java`
- **现状：** 已有 `shouldDetectCycles` 和 `shouldTraceBranchingCalls` 测试通过，但**未覆盖跨分支共享节点的重新访问场景**（本次修复的核心场景）
- **建议新增测试用例：** 构造两个端点共享公共依赖的调用图，验证第二个端点能完整追踪通过共享节点的下游调用
- **风险：** 无，纯新增测试

---

## 已完成的总结

本次共完成 **19 项**优化：

| 维度 | 数量 | 示例 |
|------|------|------|
| Bug 修复 | 2 | DFS visited 跨分支污染、URL 正则过宽 |
| 死代码删除 | 7 | TaskService(328行)、docker-compose.core.yml、空文件/空导入 |
| 去重简化 | 5 | 错误响应统一、CLI 签名统一、TaskApplicationService 工厂 |
| 配置卫生 | 4 | uv 版本统一、.gitignore 补充、CI 路径过滤、argparse 迁移 |
| Java 加固 | 2 | CallGraphBuilder 异常收窄、SourceScannerCache 提取 |
| 审查修复 | 4 | SubParserAdder 提取到 `_types.py`、方法→独立函数、json import 提升、type=Path |

**净减少代码：** ~420 行（删除约 650 行，新增约 230 行）
