# Argus 剩余优化待办（2026-08-18 批次 1–5 收尾）

> 本文档记录 2026-08-18 一轮三端审计的**未完成**事项，供后续继续优化。
> 已完成的批次 1–5 见文末摘要；批次 6（大文件拆分 + 架构收敛）及
> 批次 1–5 中遗漏的次要项全部在此列出，按「三端 × 优先级」组织。
>
> 对照文档：
> - 历史已完成：[`remaining-optimization-audit-2026-08-10.md`](remaining-optimization-audit-2026-08-10.md)
> - 上一轮审计：[`remaining-optimization-audit-2026-08-10.md`](remaining-optimization-audit-2026-08-10.md)

---

## 一、本次已完成摘要（批次 1–5）

| 批次 | 内容 | 验证 |
|---|---|---|
| 1 正确性 | Java 调用图重载键碰撞（`MethodKey`）、`MavenDetector` PATH 硬编码 `;`、`SourceFileScanner` `target` 子串过宽、Python CAS SQL 私有穿透收敛、bind 吞异常语义统一、前端 `ReportView` 全量 stringify、`TaskTimeline` 竞态、`usePagedList` 卸载清理 | Python 1418 passed；前端 227 passed |
| 2 死代码 | Python `TaskQueue.is_known`/`DbPool.conn`/`with_conn`/`with_tx`/`ConnectFn`/`MatchResult.flows`/`TIMELINE_*`/browser 死回退；Java `ClasspathMode.MAVEN`/`ModuleType.isAggregating`/`MavenConfig` 7 参构造器/`MavenModule.getVersion/getPomFile`；前端 `useDialog.showDialog`/`debugBundleUrl` | 同上 |
| 3 重复收敛 | Python `utc_now_iso`/`_build_task_where`/`_FINDING_RELATION_PRIORITY`/`_row_to_flow_step`；Java `Digests`/`MavenConfig` 拷贝构造器/`CommunityClusterer` 复用 Random；前端 `severity.ts`/`stringifyParamValue`/`shortSha`/`ElTagType` | 同上 |
| 4 性能 | Java `FindingDetector` AST 遍历 4→1/`MavenExecutor` 有界缓冲；Python `get_summary` 单连接/`list_correlation_runs_by_task` 去 N+1/`recover_stale_attempts` 批量/执行流分页按页取 steps | 同上 |
| 5 索引迁移 | 新增 `0006_correlation_analysis_index.sql` 部分索引，`EXPLAIN` 确认 `analysis_id IN (...)` 走索引；同步更新 `test_migrations.py` 迁移版本断言（[0..6]） | 空库幂等 + EXPLAIN + 全量测试通过 |
| Review 修复 | ① `list_by_blackbox_run_ids` 用 ROW_NUMBER 保持「每 blackbox_run 最新一条」语义（修复 docstring 与实现不符 + supersede 场景行为变更），补回归测试；② `ReportView.reportJsonStr` 改为仅在 `reportTab === 'raw-json'` 时序列化（默认标签不再全量 stringify）；③ 删除 `count_eligible_requests`（get_summary 内联后准死代码），测试改为直接断言 `list_eligible_requests` 过滤 | Python 1418 passed；前端 227 passed |

---

## 二、未完成 —— Python

> ✅ **2026-08-24 校验更新：P1–P9 已全部在代码中落地，本节归档为历史记录。**
> 逐项证据：P1 共享 `task/repositories/pagination.py::cursor_paginate`（finding_repo 已迁移）；
> P2 `whitebox/config.py::load_execution_config` runner/recovery 共用；P3 matcher 编译复用 +
> specificity 缓存排序；P4 服务构造器已单型化为 `TaskSQLiteStorage`；P5 project/config 服务
> 参数必填、组合根注入；P6 Runner 装配期创建一次 + `report_generator` 必填；P7 container.py
> 285 行纯装配、编排移入 `correlation/application.py`；P8 四文件均降至 <1000 行（775/855/587/790）；
> P9 `_MAX_ANALYSIS_RUNS` 已删、引擎走全量查询、聚合接口改分页 + total。
> 同日清理 P4 残留的 `task/log.py` 与 `whitebox/runner.py` 两处防御性 isinstance 分支
> （依赖文件后端即时落盘的两个单测已迁移为 SQLite 注入 + 显式 flush）。

### P1. 游标分页逻辑统一（M2）

- 【文件:行号】`argus_py/task/repositories/analysis_repo.py::_paginated_query` vs `argus_py/task/repositories/finding_repo.py:67-120`
- 【现状】两处各自实现 base64+JSON 游标编解码、非法游标回退、`limit+1` 取 `has_more`；`finding_repo` 用「`created_at < ? OR (created_at = ? AND finding_id > ?)`」手写 keyset，`analysis_repo` 用通用前缀 keyset，语义重复且行为可能分化。
- 【建议】提取共享 `cursor_paginate(conn, table, order_cols, where, params, cursor, limit)` 工具；`finding_repo` 迁移到通用实现。
- 【预期收益】单点维护游标语义；`finding_repo` 约 40 行手写分页可删。

### P2. 白盒配置恢复去重（M9）

- 【文件:行号】`argus_py/whitebox/recovery.py:194-203` vs `argus_py/whitebox/runner.py:109-114`
- 【现状】两者都做「`whitebox_config_json` → `PersistedWhiteboxConfig.model_validate_json(...).to_execution_config()` 否则 `WhiteboxTaskConfig.from_legacy_parameters(...)`」的还原。
- 【建议】抽 `whitebox/config.py::load_execution_config(task) -> ExecutionWhiteboxConfig`，runner 与 recovery 复用。
- 【预期收益】消除一份配置还原副本，避免两处行为分化。

### P3. matcher 重复编译与重复 specificity（L4/L5）

- 【文件:行号】`argus_py/correlation/matcher.py:264-279`、`:451-453`
- 【现状】(1) `build_indices` 对 templated 端点先为 method 索引算 `compiled/has_dw/min_seg`，随后为 path_only 索引**再算一遍**相同的 `compiled`/`has_dw`；(2) `_match_template` 排序时 `matched.sort(key=_compute_specificity)` 后又对 `matched[0]` 与每个 tie 重算 specificity。
- 【建议】(1) 先算一次 `compiled`/`has_dw` 两处索引复用；(2) 排序时缓存 specificity 到元组，tie 比较直接取缓存。
- 【预期收益】端点模板多时减少一半 `re.compile` 与段解析；候选端点多时减少 O(n) 次重复计算。

### P4. 存储双后端收窄（H3/L2/L10/L11，批次 6.1）

- 【文件:行号】`argus_py/task/application.py`（约 30 处 `isinstance(storage, TaskSQLiteStorage)`）、`argus_py/task/read.py:39-161`、`argus_py/task/lifecycle.py:180-191`、`argus_py/task/storage.py:37-96`（`TaskFileStorage`）
- 【现状】生产容器只构造 `TaskSQLiteStorage`（`runtime/container.py:181`），`TaskFileStorage` 仅测试/类型注解引用；但 application/read/lifecycle 到处保留双后端 `isinstance` 分支，FileStorage 回退路径生产永不执行。
- 【建议】把存储收窄为单一 `TaskSQLiteStorage` 类型（测试若需文件后端用独立 fixture），删除死回退分支；或至少收敛为一个「获取 storage 并判型」的 helper。
- 【预期收益】删除数百行死分支，降低「改 SQLite 漏改 FileStorage」风险。

### P5. 领域服务默认参数自建基础设施（L10）

- 【文件:行号】`argus_py/project/service.py:24-25`、`argus_py/config/service.py:30-31`
- 【现状】`storage or ProjectSQLiteStorage()`、`task_read_service or TaskReadService(TaskSQLiteStorage())`——缺省时领域服务自行构造共享存储（触发 `init_database` + `get_db_pool`），违反「共享资源由组合根创建」。
- 【建议】改为必填参数；缺省构造移到容器/测试工厂。
- 【预期收益】消除「领域服务自行创建共享状态」边界破坏点。

### P6. TaskRunner 每任务新建（L11）

- 【文件:行号】`argus_py/infra/worker.py:216-221`、`argus_py/execution/runner.py:81`
- 【现状】`_run_task` 每任务 `new` 一个 `TaskRunner`；`report_generator=None` 时 `runner.py:81` 每任务新建 `ReportGenerator()`（容器已持有单例 `container.report_generator`）。
- 【建议】TaskRunner 在 Worker 启动时建一次复用；或 worker 层保证 `report_generator` 非 None。
- 【预期收益】避免重复初始化；对齐「Runner 依赖由组合根装配」演进目标。

### P7. 组合根收敛（H4，批次 6.2）

- 【文件:行号】`argus_py/runtime/container.py:281-525`（6 个嵌套关联编排函数）、`argus_py/task/application.py:903-940`、`container.py:410-417`
- 【现状】组合根除装配外还承载「自动绑定同项目同快照分析」「UNVERIFIED 回退」「bb_done→READY/WAITING_BLACKBOX」等业务规则，其中「黑盒是否完成→READY/WAITING_BLACKBOX」判定在 `container.py`/`application.py` **三处重复**；快照回退/alignment 判定两处概念重复。
- 【建议】回调收敛为独立 `correlation/application.py` 编排服务，组合根只注入 `storage/lifecycle/report_generator` 并装配回调。
- 【预期收益】`container.py`（619 行）回归「纯装配」；消除三处状态推进漂移；便于单测。

### P8. 超大文件拆分（M8，批次 6.3）

- `argus_py/task/application.py`（1443 行）：任务编排 + 关联操作（bind/retry/recalc）+ 报告聚合 + 5 个模块级 dict 转换器混杂。建议关联操作与 `build_correlation_report_data`/`_correlation_run_to_dict` 迁到 `correlation/application.py` 或 `task/correlation_presenters.py`。
- `argus_py/whitebox/runner.py`（1389 行）：runner 编排 + `_map_findings`/`_build_projection_data`/`_evaluate_completeness`/`_serialize_whitebox_result` 混杂。建议投影构建与序列化迁到 `whitebox/projection.py`（两套对 `WhiteboxResult` 的字段映射集中后可审视去重）。
- `argus_py/task/repositories/correlation_repo.py`（1376 行）：blackbox_run/correlation_run+attempt/evidence/finding_evidence 四个聚合混在一个类。建议按聚合拆 2～3 个 repository（行映射留 `mappers.py`）。
- `argus_py/task/repositories/analysis_repo.py`（1063 行）：行映射（~300 行）+ CRUD + 投影写入 + 分页。建议行映射并入 `mappers.py`，投影写入/分页抽私有 helper。

### P9. 报告聚合固定 limit 静默截断（L8）

- 【文件:行号】`argus_py/task/application.py:1418`（`list_finding_evidence(..., limit=500)`）、`:1303-1305`（`list_unmatched_requests(..., limit=50)`）、`:624`（`_MAX_ANALYSIS_RUNS = 200`）
- 【现状】报告聚合按固定 limit 取数，超出时报告数据静默不全。
- 【建议】改用全量查询（如已有 `list_all_analysis_findings`）或显式 `total` 判断 + 截断标记。
- 【预期收益】避免大型关联报告缺数据。

---

## 三、未完成 —— Java

> ✅ **2026-08-24 校验更新：J1–J5 已全部在代码中落地。**
> J1：新增 `application.JobStatus`/`JobEvent` 应用层模型，`AnalysisJobService` 只产出领域
> 状态（`snapshot()`），`api.AnalysisJobStatusMapper` 负责拷贝为 wire DTO；wire JSON 字段
> 不变；ArchUnit 新增 `serviceOrchestrationMustNotDependOnHttpDtos` 门禁，并同步更新
> `docs/architecture.md` 边界描述。
> J2：删除 `MavenClasspathResolver`/`LegacyClasspathResolver`/`MavenExecutor` 无 progress
> 重载、`ModuleClassifier` 三个 1 参包私有方法；`ClasspathResult.fromJars` 下移为
> `ProjectAnalyzerServiceTest.classpathFromJars`。
> J3：作业相关异常（`NoSuchElementException`→404、`IdempotencyConflictException`→409、
> 新增类型 `JobNotCompleteException`→409）收编到 `AnalysisExceptionHandler`，全部返回
> ProblemDetail 统一响应体；Controller 移除逐条 try/catch。基础设施层的
> `IllegalStateException` 不受影响仍走 500。
> J4：新增 `MavenDetectorTest`（探测链 + 注入 env + `;`/`:` 分隔符）、
> `ClasspathFileReaderTest`（`;` vs `:`、存在性过滤、空/缺失文件降级）、
> `JavaVersionDetectorTest`（pom release/source/java.version 优先级、gradle 三种写法、默认值）。
> J5：`AnalysisJobService`（529 行）拆出包内独立类 `AnalysisJob`（CAS 状态机，198 行）与
> `JobProgress`（25 行），service 降至 334 行只留编排与幂等；`ProjectIndexCache` 抽出
> `SourceFingerprint`（含 isFingerprintInput 规则与规范化摘要），缓存类降至 436 行聚焦
> LRU/权重/单飞。均为等价重构，无行为变更。

### J1. AnalysisJobService 依赖 HTTP wire DTO（M4，批次 6 架构边界）

- 【文件:行号】`java_analyzer/src/main/java/com/argus/analyzer/service/AnalysisJobService.java:3-4`、`:467`、`:473-484`
- 【现状】作业状态机内部用 `api.dto.AnalysisJobStatusResponse`/`AnalysisJobEvent` 作返回值与事件模型，应用编排层直接依赖 HTTP 契约。O-11 已把 `AnalysisResult→AnalyzeResponse` 收敛到 adapter，但作业状态/事件 DTO 仍留在 service 内；ArchUnit 只挡 `domain/application`，未挡 `service→api.dto`。
- 【建议】domain/application 引入 `JobStatus`/`JobEvent` 领域模型，service 只产出领域状态，Controller 再映射为 `api.dto.AnalysisJobStatusResponse`。
- 【预期收益】应用编排与 wire 契约解耦，作业状态模型可脱离 Spring 单测。

### J2. 剩余死代码重载（M5 未清理部分）

| 位置 | 说明 |
|---|---|
| `MavenClasspathResolver.java:32-34`/`:40-42` | 无 progress 的两个 `resolve` 重载（门面已纯委托，无业务逻辑） |
| `LegacyClasspathResolver.java:39` | `resolve(Path, MavenConfig)` 2 参重载 |
| `MavenExecutor.java:56-59`/`:77-81` | `generateClasspath`/`generateClasspathForModule` 无 progress 重载仅测试用 |
| `ModuleClassifier.java:133/187/246` | `classifySingle(module)`/`scanSignals(module)`/`scoreModule(module)` 1 参包私有仅测试用 |
| `ClasspathResult.java:45` | `fromJars()` 仅测试用 |

- 【建议】删除，或把「仅测试用」的 factory/helper 下移 test 侧；删无 progress 重载防止误用绕过取消通道。

### J3. 错误映射不一致（L6）

- 【文件:行号】`AnalysisController.java:75-109`；`AnalysisExceptionHandler.java:13-32`
- 【现状】`IdempotencyConflictException`/`NoSuchElementException`/`IllegalStateException` 在 Controller 里逐条 try/catch 转 `ResponseStatusException`，而 `RejectedExecutionException`/`IllegalArgumentException` 走全局 advice，两套机制并存。
- 【建议】把作业相关异常收进 `AnalysisExceptionHandler`（或统一异常码映射），Controller 保持薄。
- 【预期收益】错误映射单点、可测。

### J4. 测试缺口（M9）

- 【现状】以下生产类无对应单测：`MavenDetector`、`JavaVersionDetector`、`ClasspathFileReader`、`LegacyClasspathResolver`、`SourceFileScanner.scan`。
- 【建议】优先补 `MavenDetector`（含 Linux/Windows PATH 分隔符）、`ClasspathFileReader`（`;` vs `:`）、`JavaVersionDetector`（pom/gradle 版本号）。
- 【预期收益】锁定检测/解析边界行为，防回归。

### J5. 超大文件拆分（L1/L2，批次 6.4）

- `AnalysisJobService.java`（516 行）：`AnalysisJob` CAS 状态机（:330-496）+ `JobProgress`（:499-515）提为独立包内类，service 只留编排与幂等（降到 ~300 行）。
- `ProjectIndexCache.java`（488 行）：抽 `SourceFingerprint`（含 `isFingerprintInput` 规则，:405-461），缓存类聚焦 LRU/权重/单飞。

---

## 四、未完成 —— 前端

> ✅ **2026-08-24 校验更新：F1–F3 已全部在代码中落地（含 F3-1～F3-5，见下文 F3 批注）。**
> F1：`WhiteboxReportView.vue` 新增局部工厂 `makeCursorList(fetcher, limit)`，返回
> `reactive` 包装的 `{items,total,hasMore,loading,load,loadMore,reset}`，五个子资源
> （endpoints/callNodes/flows/findings/clusters）各收敛为一行声明，删除约 70 行重复样板，
> 「未选中 run 不发请求」守卫语义保留在工厂内。
> F2：新增共享子组件 `report/ExtrasSection.vue`（折叠开关 + chevron + 内容插槽）与
> `report/ReportScreenshot.vue`（截图展开 + 路径 code + AuthenticatedImage + lightbox
> 事件透传），`StepCard`/`FindingCard` 删除各自近乎逐字相同的
> `.extras-toggle/.chevron/.extras-content/.screenshot/.screenshot-path` 模板与 scoped 样式；
> 卡片内 meta 网格仍在使用的 `code{}` 与 `.url-text` 因 scoped 样式无法跨组件生效而保留在两卡片内。

### F1. WhiteboxReportView 五段 usePagedList 样板（7）

- 【文件:行号】`frontend/src/components/task/WhiteboxReportView.vue:218-306`
- 【现状】endpoints/callNodes/flows/findings/clusters 五个子资源各自重复「`usePagedList(fetcher, {limit, cursor:true})` + 解构 + `loadX()`/`loadMoreX()` 两个 wrapper」约 16 行模板，共约 90 行；仅 limit 与 fetcher 不同。
- 【建议】抽局部工厂 `makeCursorList(fetcher, limit)` 返回 `{items,total,hasMore,loading,load,loadMore}`，五处改为一行声明。
- 【预期收益】删除约 60-80 行重复，新增子资源列表不易漏样板。

### F2. StepCard/FindingCard CSS 与结构重复（6）

- 【文件:行号】`frontend/src/components/task/report/StepCard.vue:314-421` vs `frontend/src/components/task/report/FindingCard.vue:262-353`
- 【现状】`.extras-toggle/.chevron/.extras-content/.screenshot/.screenshot-path/.url-text/code` 等样式几乎逐字相同（各约 60-70 行），截图展开 + lightbox 弹层结构也一致。
- 【建议】抽共享 `<ReportScreenshot>`/`<ExtrasSection>` 子组件（或提到共享样式），两卡片复用。
- 【预期收益】消除双份 CSS 漂移，减少 scoped 样式体积。

### F3. 大组件拆分（11，批次 6.5）

> ✅ **2026-08-24 校验更新：F3-1～F3-5 已全部在代码中落地。**
> ① `useTasks.ts`（545→67 行薄装配）：拆出 `useTaskForm.ts`（表单状态/payload 构造/校验/
> autoFillLimits 推断防抖/对话框开关）与 `useTaskActions.ts`（start/retry/delete），
> `useTasks` 仅做组合并 re-export `TaskFormState`/`defaultTaskFormState` 保持旧导入路径；
> ② `useConsoleApp.ts`（273→205 行）：抽 `useTopBar.ts`（viewTitle 计算 + error/message
> 节流 toast），WS 重连编排内聚为 `useRuntimeEvents.watchEventStream`；
> ③ `TaskFormDialog.vue`：移除 3 个薄 watch 直接写父表单与 `vue/no-mutating-props` 豁免，
> goal/taskType/startUrl 改经 `infer-inputs` 显式事件回传父级驱动推断
> （`useTaskForm.applyInferInputs`），保存改为单一快照事件 `save(snapshot)` 由
> TasksView 合入父表单后再走统一校验提交；add/remove 参数行改弹窗本地处理，
> 死代码 addParam/removeParam 从 useTaskForm/useConsoleApp 删除；
> ④ 新增通用 `common/StatCard.vue`（含 confirmed 强调/hint 提示/el-tag/note/show 配置项），
> CorrelationTab 总览 4 卡片 + 数据质量 15 行统计全部改配置数组驱动，删除约 130 行手写模板与样式；
> ⑤ 新增 `whitebox/WhiteboxBuildLog.vue`，TaskTimeline（668→415 行）只保留数据加载、
> WS 订阅、reloadTick 权威重拉与时间线渲染分支。

- `frontend/src/composables/useTasks.ts`（545 行）：拆 `useTaskForm`（表单+payload+校验+autoFillLimits）与 `useTaskActions`（start/retry/delete/save）。
- `frontend/src/composables/useConsoleApp.ts`（273 行）：result 暴露约 60 个键；可抽 `useTopBar`（viewTitle/toast 节流监听）与独立 WS 编排函数。
- `frontend/src/components/task/TaskFormDialog.vue`（558 行）：「打开快照 + 3 个薄 watch 写回父表单 + onSave Object.assign」双向同步脆弱（`vue/no-mutating-props` 被关闭），简化为局部副本 + 单一 save payload，仅 goal/startUrl/taskType 显式事件回传父级做推断。
- `frontend/src/components/task/whitebox/CorrelationTab.vue`（627 行）：总览 4 卡片 + 采集质量约 30 行 stat 行全手写模板，改数据驱动 `<StatCard>`/配置数组循环。
- `frontend/src/components/task/TaskTimeline.vue`（668 行）：同时承担「执行时间线」与「白盒 build log」两套渲染分支，把 whitebox-log 拆为独立组件。

---

## 五、建议实施顺序

```text
第 1 步（低风险去重收尾）
  P1 游标分页统一 → P2 配置恢复去重 → P3 matcher 微去重
  J2 剩余死代码重载 → J3 错误映射统一 → F1 usePagedList 样板 → F2 CSS 去重

第 2 步（测试缺口）
  J4 MavenDetector / ClasspathFileReader / JavaVersionDetector 单测

第 3 步（架构收敛，逐项独立提交+验证）
  P4 存储双后端收窄（依赖 P 已就位的公开方法）→ P5/P6 默认参数与 Runner 装配
  → P7 组合根收敛 → J1 AnalysisJobService 领域状态模型

第 4 步（超大文件拆分，每项补单测后再删旧路径）
  P8 Python 四大文件 → J5 Java 两大文件 → F3 前端四大组件
```

## 六、验证方式

- Python：`uv run ruff check argus_py tests scripts`、`uv run ruff format --check ...`、`uv run mypy argus_py`、`uv run pytest tests/unit tests/integration -q --tb=short`。
- 前端：`pnpm exec eslint src/`、`pnpm exec vue-tsc --noEmit`、`pnpm test`、`pnpm build`（涉构建时）。
- Java：补单测后 **不执行 Maven 编译/测试，由用户自行验证**（遵守项目规则）。
- 架构改动若触及 `docs/architecture.md` 基线，必须同步更新该文档并说明兼容/迁移/回滚。

---

## 附：本次已完成项速查（供快速确认不重复劳动）

- **已做**：`MethodKey` 键统一、`File.pathSeparator`、`SourceFileScanner` target 段匹配、CAS SQL 公开方法（`requeue_stale_task`/`mark_stale_task_terminal`/`list_stale_whitebox_tasks`）、`_claim_and_execute_matching_sync`、`utc_now_iso`、`_build_task_where`、`Digests`、`MavenConfig` 拷贝构造器、`CommunityClusterer` Random 复用、`FindingDetector` 单遍历、`MavenExecutor` 有界缓冲、`get_summary` 单连接、`list_by_blackbox_run_ids`、`recover_stale_attempts` 批量、`list_flow_steps_by_flow_ids`、`0006` 迁移、前端 `severity.ts`/`stringifyParamValue`/`shortSha`/`ElTagType`/`usePagedList` 卸载守卫/`TaskTimeline` 竞态/`ReportView` memoized stringify。
- **Review 修复（同日）**：`list_by_blackbox_run_ids` ROW_NUMBER 去重（每 blackbox_run 最新一条）+ 回归测试、`ReportView.reportJsonStr` 依赖 `reportTab` 门槛、删除 `count_eligible_requests`（get_summary 内联后准死代码）+ 测试改造、`test_migrations.py` 迁移版本断言更新为 [0..6]。
- **未做（本清单）**：无——P1–P9 已于 2026-08-24 完成并归档（见第二节批注）；J1–J5 已于
  2026-08-24 完成（见第三节批注）；F1–F3 已于 2026-08-24 完成（见第四节批注）。
