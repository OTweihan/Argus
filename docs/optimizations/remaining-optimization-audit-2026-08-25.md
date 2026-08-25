# Argus 剩余优化待办（2026-08-25 批次）

> 本文档记录 2026-08-25 一轮三端（Python / Java / 前端）审计的发现与完成状态。
> 历史批次见 [`remaining-optimization-audit-2026-08-18.md`](remaining-optimization-audit-2026-08-18.md)、
> [`follow-up-optimizations.md`](follow-up-optimizations.md)。
>
> 本轮共 12 项修复，按「高优先级正确性 → 中优先级性能/一致性」分四批实施，
> 每批独立验证：Python ruff/mypy/pytest 全量、Java `mvn test`、前端
> eslint/vue-tsc/pnpm test。

---

## 高优先级（正确性缺陷）

### 1. 关联匹配在异步路径直接阻塞事件循环 ✅ 已完成

- 【文件】`argus_py/correlation/application.py`
- 【现状】黑盒完成回调 `claim_and_execute` 与白盒成功回调 `on_whitebox_analysis_succeeded`
  在事件循环上内联执行 `execute_correlation`（全量加载投影 + match_batch + 批量 INSERT
  的纯 CPU+同步 SQLite 重活），大项目收尾时冻结整个服务（API/WS/其他任务）。
- 【修复】`_execute_correlation` 改为 `run_in_thread(self._execute_correlation_sync)`；
  `claim_and_execute` 的认领阶段与 FAILED 兜底写入、`on_whitebox_analysis_succeeded`
  的绑定/认领阶段（收敛为 `_bind_and_claim_waiting`）、`regen_report_after_attempt`
  的前置读全部经线程执行。行为等价，多个等待运行的绑定先于其执行完成（各运行独立）。

### 2. correlation attempt 崩溃恢复从未接线 ✅ 已完成

- 【文件】`argus_py/infra/worker.py`（`_reconcile_stale_tasks`）
- 【现状】`recover_stale_attempts()` 只有测试调用；进程在 claim 后 complete 前崩溃 →
  CorrelationRun 永久卡 RUNNING（claim CAS 要求 READY 永远失败），只能手工 recalc 逃生。
- 【修复】Worker 启动 reconciliation 追加 `recover_stale_attempts()`（线程内执行、
  失败不阻断启动）；新增 worker 接线与恢复容错两个测试。

### 3. Java single-flight 异常传染 ✅ 已完成

- 【文件】`java_analyzer/.../support/ProjectIndexCache.java`（`getOrCompute`）
- 【现状】follower 直接 `existing.join()`：领导者的 `JobCancelledException` 以
  `CompletionException` 包装传染给同 key 无关作业（B 被误标 CANCELLED）、瞬时失败原样
  传染；同步 `/analyze` 作 follower 时抛裸 CompletionException → 500；follower 一律计
  cacheHits。
- 【修复】follower catch 后解包：取消视为 single-flight miss 就地重算（等领导者 finally
  清理后重试，上限 5 次防活锁）；其余异常重抛原始类型；仅成功 join 计 hit。
  新增 2 个并发测试（跟随者不被取消传染 / 失败解包为原始类型）。

### 4. 前端 WS patch 触发 correlationRunId 重查循环 ✅ 已完成

- 【文件】`frontend/src/views/TasksView.vue`
- 【现状】`watch(selectedTask)` 监听对象引用，而运行中任务的每个 WS patch 都整体替换
  对象 → correlationRunId 反复置空重查，关联 pane 反复卸载重挂、分页/滚动状态丢失。
- 【修复】监听源改为 `() => selectedTask.value?.taskId ?? null`，快照守卫保留。

---

## 中优先级

### 5. ClasspathFileReader Windows 盘符劈裂 ✅ 已完成

- 【文件】`java_analyzer/.../env/classpath/parser/ClasspathFileReader.java`
- 【现状】分隔符启发式 `contains(";") ? ";" : ":"` 被单条目 classpath 击穿：
  Windows 单 jar 文件 `C:\...` 按 `:` 劈成 `"C"`+相对路径 → 缓存永远失效/路径损坏，
  静默降级 source-only。
- 【修复】无 `;` 但以盘符前缀（`^[A-Za-z]:[\\/]`）开头时整行作为单条目；
  补「Windows 盘符单条目」测试（跨平台断言 warning 携带完整未劈裂路径）。

### 6. 白盒结果序列化在事件循环上执行 ✅ 已完成

- 【文件】`argus_py/whitebox/runner.py`
- 【现状】`map_findings`（每 finding 一次 `Path.resolve()`）、巨型 dict 构建、
  数十 MB 级 `json.dumps`、sha256、投影行构造都在事件循环上。
- 【修复】抽 `_prepare_success_result` / `_AnalysisPersistPayload` 两个同步函数经
  单次 `run_in_thread` 计算，事务写入维持两次不变（DB 结果等价）。

### 7. 白盒 pause/resume 僵尸 RUNNING ✅ 已完成（方案①：禁止无效 resume）

- 【文件】`argus_py/task/application.py`（`resume_task`）
- 【现状】白盒是一次性分析型 handler：暂停后远端作业完成、结果落盘但被 PAUSED
  阻止终态推进，handler 退出；此时 resume 把状态翻回 RUNNING 却永远无人再执行。
- 【修复】resume 前校验队列调度状态，无活跃执行（`scheduler_status != "running"`）
  则抛 `TASK_NOT_EXECUTING`（409）并提示改用 restart；新增正反两例单测
  （含「状态保持 PAUSED 不被翻回」断言）。

### 8. AnalysisJobService 容量准入计入终态作业 ✅ 已完成

- 【文件】`java_analyzer/.../service/AnalysisJobService.java`
- 【现状】准入 `jobs.size() >= maxJobs` 把保留期内（默认 1800s）全部终态作业计入，
  高完成速率下已完成作业挤爆额度 → 假性 503。
- 【修复】准入只统计 `isActive()`（PENDING/RUNNING）作业；终态仍留 jobs 表供查询/
  幂等，由 TTL 清理回收。补「终态不占额度」测试。

### 9. SourceScannerCache 持锁构建 + JarTypeSolver 句柄泄漏 ✅ 已完成

- 【文件】`java_analyzer/.../support/SourceScannerCache.java`、`SourceFileScanner.java`、
  新增 `JarTypeSolverPool.java`
- 【现状】(a) 所有读写在一个实例锁上且 `entry()` 持锁执行全树 POM 遍历——项目 X 建
  索引期间项目 Y 全部查询阻塞；(b) 每次 scan 为每 jar `new JarTypeSolver` 从不关闭，
  fd/zip 句柄累积且中央目录重复解析。
- 【修复】(a) per-path single-flight：LRU 结构 O(1) 操作持锁，构建移到首个请求者线程，
  同路径并发请求 join 同一 future（异常解包重抛）；(b) 进程级有界复用池
  （键 = 规范路径+mtime+size，LRU 上限 32，淘汰才关闭）。**不能按 scan 关闭**——AST
  在后续 pass 中对 jar 符号做惰性解析，提前关闭会让跨 jar 解析静默退化为 unresolved。

### 10. 指纹口径不一致 + legacy 缓存无新鲜度校验 ✅ 已完成

- 【文件】新增 `support/BuildOutputFilter.java`；`SourceFingerprint.java`、
  `SourceFileScanner.java`、`LegacyClasspathResolver.java`、`ClasspathCacheManager.java`
- 【现状】(a) 扫描器排除 `target/**` 但指纹不过滤任何目录——生成产物参与指纹却从不
  参与扫描：缓存键随构建状态漂移 + 无意义哈希 IO；Gradle `build/` 两层都不排除。
  (b) legacy 路径命中 `.argus/classpath.txt` 仅凭 hasValidJars 直接返回，根 pom/
  settings/JDK 变更后静默使用陈旧 jars（模块感知路径有 meta 校验，两条路径策略不一）。
- 【修复】(a) 抽共享谓词 `BuildOutputFilter.isUnder`（`target/build/out` 按段精确匹配），
  扫描与指纹共用；(b) legacy 缓存增加 `.argus/classpath.meta` 元数据校验
  （复用 CacheMetadata 口径，根 pom 取 `sourcePath/pom.xml`），失效走既有生成链并在
  成功后刷新 meta，失败保留既有 stale fallback 兜底。
- 【注意】指纹口径变化使旧缓存键一次性自然失效（TTL 30min，无需干预）。

### 11. CancellationToken 双线程访问竞态窗口 ✅ 已完成

- 【文件】`argus_py/task/lifecycle.py`
- 【现状】事件循环线程与 IO 线程都会访问 token 注册表，懒创建是跨线程
  check-then-act（非原子）——双创建窗口下败者的取消/暂停信号写入孤儿 token 丢失。
- 【修复】注册表加 `threading.Lock`（信号布尔位幂等且 GIL 下读写原子，锁只保护
  创建窗口）；类注释补充双线程访问协议。选最小方案而非迁移变更所有权。

### 12. 前端异步加载守卫收尾 ✅ 已完成

- 【文件】`WhiteboxReportView.vue`、`useTaskViewActions.ts`、`useTraceList.ts`、
  `api/task/index.ts`、`usePagedList.ts`
- 【现状】三处异步加载无代次守卫/中止：诊断加载跨 run 串台；详情弹窗快速切换串数据；
  useTraceList 契约声明支持响应式 taskId 却无防护。白盒子资源 API 一半支持 signal，
  usePagedList 只能丢弃响应不能真正取消请求。
- 【修复】
  - `loadDiagnostics` 补 abort + 身份校验（对齐同文件 F7/F8 口径），reset/unmount 中止；
  - `showTaskDetail` 补代次计数 + AbortController（对齐 selectTask 模式）；
  - `useTraceList` 补 requestSeq + abort + scope dispose 中止；
  - 白盒子资源 6 个 API 函数与 `getTaskTraces` 统一补 `options:{signal}`；
  - `usePagedList` 分页请求对象携带每次独立的 `AbortSignal`，新 load/reset/卸载时
    abort 旧请求（真正取消在途带宽），被取消的响应静默丢弃不写错误。
- 【测试】`usePagedList.spec` 断言改子集匹配并新增 signal 中止用例（228 passed）。

---

## 验证记录

| 范围 | 命令 | 结果 |
|---|---|---|
| Python | `ruff check` + `ruff format --check` + `mypy argus_py` | 全部通过 |
| Python | `pytest tests/unit tests/integration -q` | **1425 passed, 5 skipped** |
| Java | `mvn test`（本轮已获用户授权执行） | **BUILD SUCCESS：195 tests, 0 failures**（新增 4 例） |
| 前端 | `eslint src/` + `vue-tsc --noEmit` | 通过 |
| 前端 | `pnpm test` | **228 passed**（新增 1 例） |

## 遗留待办（已全部完成）

1. **ExecutionFlowTracer flows 体积二次膨胀** ✅ 已完成（2026-08-25 第二轮）
   - 【修复】单流步数上限 400 + 全局步数预算 5000：超限截断当前流、预算耗尽后
     跳过剩余端点；截断经 progress 发 WARN 事件、打日志，并新增
     `AnalyzerDiagnostics.flowTruncations` 记录（Java/Python 端同步镜像，
     报告 diagnostics 一并透出）。上限内行为与旧实现完全一致。
2. **TaskTimeline O(n) 事件去重** ✅ 已完成（2026-08-25 第二轮）
   - 【修复】`some()` 全数组扫描改为 Set 幂等索引（O(1)）；`MAX_EVENTS = 2000`
     有界缓冲，超限丢弃最旧事件（权威历史仍可经挂载加载/reloadTick 从 SQLite
     重取）；初始加载与服务端重拉统一走同一截断与索引重建路径。新增 4 个组件测试。
3. **大列表虚拟化** ✅ 已完成（2026-08-25 第二轮）
   - 【修复】白盒报告五个子列表（EndpointList / CallGraphViewer / ExecutionFlowList /
     ClusterList / FindingList）接入共享渲染上限守卫 `useRenderCap`（上限 500）：
     过滤/排序仍作用于全量已加载数据，仅 DOM 渲染截断前 500 行；触顶后以
     `RenderCapHint` 提示「可过滤或缩小范围」并停用继续追加的无限滚动入口，
     避免 el-table/v-for 无界累积行数导致滚动与输入卡顿。未触顶行为不变。
4. **JarTypeSolverPool 可选增强** ✅ 已完成（2026-08-25 第二轮）
   - 【修复】(a) 容量参数化：经 `argus.analysis.jar-pool.max-open-jars`（默认 256）
     Spring 注入配置，调优不再需要改代码（类注释遗留的旧值 32 已一并修正）；
     (b) 可观测性：新增 acquisitions/hits/opens/evictions 计数与 `stats()` 快照，
     首次淘汰即 WARN 提示「被淘汰 solver 的惰性解析会退化为 unresolved、考虑调大
     容量」，其后降为 debug——为数据驱动的容量调优提供依据；(c) 预热评估结论：
     刻意不做进程级预热——acquire 在扫描路径上按需打开，预热不减少首次解析总量
     只移动时机，且对全部历史 jar 预热会空占 fd/内存，与 LRU 容量目标相悖
     （javadoc 已记录论证）。
   - 【注意】`SourceFileScanner` 的 jar 池改为构造注入（保留两参便捷构造，既有
     测试不受影响）；新增 `JarTypeSolverPoolTest`（复用命中计数 / LRU 淘汰 /
     非法容量）。

### 第二轮验证记录

| 范围 | 命令 | 结果 |
|---|---|---|
| Python | `ruff check` + `ruff format --check` + `mypy argus_py` | 全部通过 |
| Python | `pytest tests/unit tests/integration -q` | **1429 passed, 5 skipped**（新增 4 例） |
| 前端 | `eslint` + `vue-tsc --noEmit` | 通过 |
| 前端 | `pnpm test` | **232 passed**（新增 4 例）→ 第二轮后 **236 passed**（再增 4 例） |
| Java | `mvn test`（已获用户授权执行；含构造器签名冲突修复） | **BUILD SUCCESS：201 tests, 0 failures, 2 skipped**（两轮共新增 6 例） |

## 行为变化说明（兼容/迁移）

- B4：对「无活跃执行的 PAUSED 任务」resume 由静默翻状态改为 409 引导 restart（正是
  本项要堵的僵尸路径，无正常流程受影响）。
- C1/C3/C5/C6：错误映射更精确（不再 500 包装）、503 语义回归并发上限、缓存键一次性
  失效、legacy classpath 在 pom/settings/JDK 变化后重新生成一次——均为预期修正。
- 无数据库迁移、无 Python↔Java wire contract 变更、无 OpenAPI schema 变化。
