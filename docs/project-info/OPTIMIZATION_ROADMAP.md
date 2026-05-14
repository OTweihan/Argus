# Argus 优化路线图

> 落盘版本，跟踪短期 / 中期 / 长期优化项的执行进度。每完成一项，请更新对应条目的状态、最后修改日期，并在“变更记录”追加一行。

---

## 进度概览

| 阶段 | 主题 | 已完成 | 待完成 |
| ---- | ---- | ------ | ------ |
| Phase 1 | 短期：可立即收益的高价值改动 | 5 / 5 | — |
| Phase 2 | 中期：可维护性 / 代码结构 / 安全 | 7 / 7 | — |
| Phase 3 | 长期：架构演进 / 工程基建 | 0 / 6 | 全部 |

最近更新：2026-05-14。

---

## Phase 1 · 短期（高价值、低成本、范围聚焦）

### 1.1 前端按需加载 + 路由懒加载 — ✅ 已完成（2026-05-13）

- `frontend/package.json`：新增 `unplugin-vue-components` 开发依赖。
- `frontend/vite.config.ts`：接入 `ElementPlusResolver` 模板自动按需 import + 自动注入对应 CSS；`rollupOptions.output.manualChunks` 拆出 `vendor-vue` 与 `vendor-element-plus` 两个独立 chunk；`dts: src/components.d.ts`。
- `frontend/.gitignore`：忽略自动生成的 `frontend/src/components.d.ts`。
- `frontend/src/main.ts`：移除全局 `import "element-plus/dist/index.css"` 与 `app.use(ElementPlus)`；改为按需 import 命令式 API 的 CSS（`el-message`、`el-message-box`、`el-overlay`、`el-loading`），并显式 `app.directive("loading", ElLoading.directive)`。
- `frontend/src/App.vue`：`DashboardView / ProjectsView / TasksView / ModelsView` 改为 `defineAsyncComponent` 路由级懒加载；外层包裹 `<el-config-provider :locale="zhCn">` 保留中文 locale；引入 `<Suspense>` 提供 fallback。
- `frontend/src/views/TasksView.vue`：任务详情三个大体积 Tab（`ReportView` / `TaskTimeline` / `LLMDebugTab`）改为 `defineAsyncComponent`，仅在切到对应 Tab 时按需加载。

> 暂不引入 `unplugin-auto-import`：避免它对 `vue-tsc` 类型检查阶段产生干扰；命令式 API 仍走显式 import + 集中 CSS。

### 1.2 SQLite PRAGMA 一次性设置 — ✅ 已完成（2026-05-13）

- `argus_py/infra/db.py`：`connect()` 仅设置连接级参数（`foreign_keys`、`busy_timeout`）；`PRAGMA journal_mode = WAL` 是数据库级永久属性，挪到 `init_database()` 仅在初始化时执行一次，避免每次新建连接都触发额外写 IO。

### 1.3 async 路由内同步 IO 修复 — ✅ 已完成（2026-05-13）

> 真正含 `await IO` 的 async 路由保持不变。下面这些 `async def` 内部全部是同步 SQLite / 文件 IO，改回 `def` 后由 FastAPI 自动放进线程池执行，避免阻塞事件循环（影响 WebSocket 心跳、其他并发请求）。

- `argus_py/api/routes/reports.py`：`get_task_report` / `get_task_report_json` / `get_task_screenshot` 均改为 `def`。`FileResponse`、`HTTPException` 在同步路由中行为完全一致。
- `argus_py/api/routes/events.py`：`list_task_events` / `list_llm_traces` / `get_trace_detail` / `download_debug_bundle` 均改为 `def`。`download_debug_bundle` 是热点（zip 大量截图、读 trace JSONL），改 `def` 后线程池执行不再卡住事件循环。

> `argus_py/api/routes/tasks.py` 暂不改：除 `create_task` / `infer_limits` 之外的端点都依赖 `await app.<...>`（队列状态快照、scheduler 协程封装）。`create_task` / `infer_limits` 改造意义有限，留待 Phase 2 一并处理。

### 1.4 LLMClient 持久化 httpx.AsyncClient — ✅ 已完成（2026-05-13）

- `argus_py/llm/client.py`：
  - 新增私有属性 `self._http: httpx.AsyncClient | None`；首个请求时通过 `_ensure_http()` 懒创建并复用。
  - `_post_completion()` 不再 `async with httpx.AsyncClient(...)`，改用复用实例 → 同一任务期内 planner / evaluator / 重试链共享 keep-alive 连接池，省 TCP 三次握手 + TLS 握手。
  - 新增 `async def aclose()`：可重复调用、忽略关闭时异常。
  - 实现 `async with`（`__aenter__` / `__aexit__`）支持。
- `argus_py/blackbox/llm_boundary.py`：`LLMBoundaryFactory` 记录“自有 LLMClient”，新增 `aclose_owned()`；不会关闭外部注入的 default_planner / default_evaluator 所携带的 client。
- `argus_py/blackbox/runner.py`：`BlackboxRunner.run` 在 `finally` 中调用 `await self.llm_boundary.aclose_owned()`，任务结束即释放底层连接池。
- `argus_py/config/service.py`：`ModelConfigService.test_model_config` 用 `async with create_llm_client(config) as client:` 确保连通性检查后立即释放。
- `argus_py/cli/commands/llm.py`：`run_check` 使用 try / finally 在退出前 `await client.aclose()`，避免 CLI 退出时出现未关闭客户端警告。

### 1.5 trace JSONL 流式分页 — ✅ 已完成（2026-05-13）

- `argus_py/api/routes/events.py`：
  - 抽出 `_iter_filtered_trace_records(lines, trace_id_filter)` 生成器：流式逐行解析 JSONL，按 `trace_id` 过滤；遇到损坏行只 `logger.warning` 跳过，不再让 `JSONDecodeError` 直接冒泡成 500。
  - 抽出 `_serialize_trace(record)` 收敛 `LLMTraceResponse.model_validate(...).model_dump(...)`。
  - `list_llm_traces` 改用 `itertools.islice(..., skip, stop)`，仅对窗口内记录做 Pydantic 验证 + dump；窗口外的行只做轻量 `json.loads` 即被跳过。
  - `get_trace_detail` 改为 `next(_iter_filtered_trace_records(...), None)` 命中即早退，去重原循环逻辑。
- `tests/unit/test_platform_boundaries.py`：
  - 因 1.3 已把 `list_task_events / list_llm_traces / get_trace_detail / download_debug_bundle` 改成同步 `def`，原先 9 个 `@pytest.mark.asyncio + await event_routes.<...>` 测试会抛 `TypeError`。本轮一并去掉装饰器与 `await`，改为同步调用。
  - 新增 `test_list_llm_traces_pagination_streaming`：验证 `skip/limit` 分页正确性，并断言流中混入损坏 JSON 行时被静默跳过、不抛 500。

> 行为变化：trace JSONL 中如出现非法 JSON 行，旧实现会抛 500；新实现按 warning 跳过。这是顺手的鲁棒性提升（trace 写一半进程被 kill 时常见）。

---

## Phase 2 · 中期（结构 / 可维护性 / 安全）

### 2.1 TaskResponse / TaskSummaryResponse 公共基类 — ✅ 已完成（2026-05-14）

- `argus_py/api/schemas/tasks.py`：
  - 新增 `_TaskResponseBase(ApiModel)`：收敛 18 个共享字段（task_id … error_message）。
  - 新增 `@staticmethod _common_fields(task, scheduler_status)`：统一脱敏处理 + kwargs 构造。
  - `TaskResponse` 仅声明差异字段 `logs / findings`，`from_task` 用 `**cls._common_fields(...)` 拼接。
  - `TaskSummaryResponse` 同理，仅声明 `finding_count`。
- `populate_by_name=True` 已经由 `ApiModel` 基类承担（见 `argus_py/api/schemas/base.py`），无需额外收敛。
- 字段顺序变化：原 `TaskResponse` 字段顺序为 `... current_step, parameters, logs, findings, created_at ...`，重构后 `logs / findings` 移到子类、排在父类字段之后（即 `... error_message, logs, findings`）。**JSON 对象按规范无序**，前端不应依赖位置；OpenAPI schema 字段顺序变化属于可接受副作用。

### 2.2 BrowserActions 异常处理装饰器 — ✅ 已完成（2026-05-14）

- `argus_py/browser/actions.py`：
  - 新增 `_handle_browser_errors(action, *, timeout_msg, target_param="target")` 装饰器：统一映射 `PlaywrightTimeoutError → BrowserTimeoutError`、保留 `BrowserError` 子类原样、其他 `Exception → BrowserActionError`；通过 `inspect.signature` 在装饰时解析签名，运行时只在异常路径做 `sig.bind` 提取 target。
  - 应用到 `navigate`（`target_param="url"`）、`click` / `fill` / `press` / `select_option`（默认 `target`）、`wait_for_load_state`（`target_param="state"`）共 6 个方法。
  - `screenshot` 不应用：原本只有 `BrowserError` + 通用 `Exception` 两个分支，且 target 是动态拼接路径（`screenshot_dir / name`），保留原样更直接。
- 异常消息文本与映射规则与改造前 1:1 一致，对外契约不变。

### 2.3 Repository `with_conn` / `with_tx` 上下文 helper — ✅ 已完成（2026-05-14）

- `argus_py/infra/db.py`：
  - 新增类型别名 `ConnectFn = Callable[[], sqlite3.Connection]`。
  - 新增 `@contextmanager with_conn(connect_fn)`：替代 `with closing(connect_fn()) as conn:` 纯读模板。
  - 新增 `@contextmanager with_tx(connect_fn)`：在 `with_conn` 基础上嵌套 `with conn:` 事务上下文，用于写路径，`__exit__` 时按 SQLite Connection 协议自动 commit / rollback。
- 调用方改造：
  - `argus_py/task/repositories/task_repo.py`：5 个方法（save / exists / load / delete / update_task / list_tasks / count_tasks / list_task_summaries）全部切到 `with_conn` / `with_tx`，并删除已不再使用的 `import json`。
  - `argus_py/task/repositories/log_repo.py`、`event_repo.py`、`finding_repo.py`：构造函数标注 `ConnectFn` 类型，方法体改用 helper。
  - `argus_py/project/storage.py`：在 `__init__` 里建一个 `self._connect = lambda: connect(self.db_path)`，6 个方法全部切到 helper。
  - `argus_py/config/model_storage.py`：同上，5 个方法全部切到 helper。
- `argus_py/infra/db.py` 的 `init_database` 与 `argus_py/core/crypto.py:_has_encrypted_api_keys` 保留 `closing(connect(...))` 模板：前者是初始化路径（含 PRAGMA + 多个 schema 切换），后者是启动期检测 + 异常吞噬，刻意不走通用 helper 以避免连锁影响。

### 2.4 TaskService facade 简化或拆分 — ✅ 已完成（2026-05-14）

> 现状：`TaskService` 已经是纯 facade，全部业务下沉到 `TaskLifecycleService` / `TaskQueryService` / `TaskLogService` / `TaskTimelineService`，本轮主要清理子服务之间的重复样板与 facade 中的 None 分支。

- 新增 `argus_py/task/_base.py`：定义 `_StorageEventBase`，统一收敛子服务公共部分 —— 持有 `storage` + 可选 `event_publisher`、`_resolve_task(task | str)` 还原任务对象、`_publish` 在 publisher 为空时静默发事件。同时 re-export `TaskEventPublisher = Callable[[str, str, dict], None]`。
- `argus_py/task/lifecycle.py`：`TaskLifecycleService` 改为 `_StorageEventBase` 子类；`__init__` 仅扩展 `_cancellation_tokens`；删掉重复的 `_resolve_task` / `_publish` 实现；`TaskEventPublisher` 改为从 `_base` re-export。
- `argus_py/task/log.py`：`TaskLogService` 同样改为 `_StorageEventBase` 子类；删掉重复的 `_resolve_task` / `_publish` / 局部 `TaskEventPublisher` 别名。
- `argus_py/task/event.py`：新增 `_NullTimelineService` Null Object，`emit / list_by_task / delete_by_task` 全部空操作；签名与 `TaskTimelineService` 对齐。
- `argus_py/task/service.py`：
  - `self.timeline` 类型改为 `TaskTimelineService | _NullTimelineService`，仅 SQLite 后端实例化真正服务，否则用 `_NullTimelineService()` 占位。
  - `emit_timeline` / `list_timeline_events` 删除 `if self.timeline is None` 分支，直接调用，让 facade 与未来扩展子服务调用方都不必处理 `None`。
  - 顶部加 docstring 标注新代码推荐直接通过 `service.lifecycle` / `service.query` / `service.log` / `service.timeline` 子服务调用，facade 仅为兼容存量。

### 2.5 ReportView.vue / LLMDebugTab.vue 拆分子组件 — ✅ 已完成（2026-05-14）

> 拆分原则：先抽 v-for 重复结构最强烈、且自带局部 toggle 状态的卡片；CSS 变量保留在父级 `.report-container`，子组件通过 CSS 继承直接 `var(--xx)` 使用，不需重复声明。

- 新增 `frontend/src/components/task/report/StepCard.vue`：单个执行步骤卡（timeline 节点 + 步骤详情 grid + 参数 / 截图折叠区）。`paramsOpen` / `screenshotOpen` 在子组件内自管，截图点击通过 `@open-lightbox` 事件回报父级。
- 新增 `frontend/src/components/task/report/FindingCard.vue`：单条 finding 卡（severity bar + 元信息 grid + 截图折叠）。`screenshotOpen` 子组件自管。
- 新增 `frontend/src/components/task/report/reportUtils.ts`：把原 `ReportView.vue` 内联的 `formatDate`（`Intl.DateTimeFormat("zh-CN")` 版）+ `prettyJson` 抽成共享 utility，避免 ReportView 与新子组件三处重复。注释中说明了与 `frontend/src/utils.ts` 的 `formatDate`（列表页风格）的差异，避免误统一。
- 新增 `frontend/src/components/task/debug/DebugCodeSection.vue`：可折叠代码段（chevron + title + 复制按钮 + `<pre class="dbg-code">`）。`open` 子组件自管，复制行为通过 `@copy(text)` 事件由父级调用 `navigator.clipboard.writeText`。
- `frontend/src/views/ReportView.vue`：
  - timeline 内 `v-for` 改为 `<StepCard :step :task-id @open-lightbox="openLightbox">`。
  - findings 列表改为 `<FindingCard :finding :index :task-id @open-lightbox="openLightbox">`。
  - 删除内联的 `formatDate` / `prettyJson` / `extrasOpen` / `toggleExtra` / `extraOpen` / 第二个 step 参数；`openLightbox` 简化为接 `path` 字符串。
  - 删除已迁出的 ~430 行 CSS：`.step-*` / `.node-*` / `.tag-*` / `.sdi-*` / `.finding-*` / `.sev-*` / `.fm-*` / `.screenshot*`，以及 720px media query 中相关条目。
  - 文件长度由 1834 行降至 1303 行。
- `frontend/src/components/task/LLMDebugTab.vue`：
  - 4 处 `<div class="dbg-section">` 块替换成 4 个 `<DebugCodeSection :title :content @copy="copyText">`。
  - 删除 `sectionsOpen` ref + `toggleSection` / `sectionOpen` 函数；`copyText` 保留，作为 emit 回调。
  - 删除已迁出的 ~80 行 CSS：`.dbg-section*` / `.dbg-sec-chevron` / `.dbg-section-copy` / `.dbg-section-body` / `.dbg-code` / `@keyframes fadeIn`。
  - 文件长度由 703 行降至 569 行。

### 2.6 useTasks debounce 抽 useDebounceFn helper — ✅ 已完成（2026-05-14）

- 新增 `frontend/src/composables/useDebounceFn.ts`：返回带 `cancel` / `flush` 方法的 debounced 函数；通过 `getCurrentScope() + onScopeDispose(cancel)` 自动绑定 Vue effect scope，组件卸载时自动清理 pending 计时器，调用方再不需要手写 `onUnmounted`。
- `frontend/src/composables/useTasks.ts`：`autoFillLimits` 改为 `useDebounceFn(autoFillLimits, 400)`；`taskForm.goal` / `taskForm.startUrl` 两个 watcher 共享同一 debounced 函数，行为与原 `goalTimer` 共享计时器的语义一致。
- `frontend/src/composables/useTaskList.ts`：`taskSearchQuery` 的 300ms 防抖改用 helper，删除 `searchTimer` 局部变量。
- `frontend/src/composables/useTaskEvents.ts`：`scheduleRefresh` 350ms 防抖改用 helper，删除 `refreshTimer` 与 `onUnmounted` 清理代码。

### 2.7 安全细节收敛 — ✅ 已完成（2026-05-14）

- **脱敏关键词集中化**
  - `argus_py/redaction/patterns.py`：新增公开权威常量 `SENSITIVE_NAME_KEYWORDS`（字段名 substring 匹配）、`SENSITIVE_VALUE_KEYWORDS`（key=value / JSON 正则匹配）、`URL_PARAM_NAMES` / `TEXT_PARAM_NAMES` / `REDACTED`，并保留旧私有别名（`_SENSITIVE_NAME_PATTERNS` 等）以避免一次性扩散修改 `argus_py/browser/snapshot.py` 等下游 import。
  - `argus_py/redaction/core.py`：`_SENSITIVE_TEXT_PATTERNS` 改由 `_build_sensitive_text_patterns()` 从 `SENSITIVE_VALUE_KEYWORDS` 动态拼装；JSON 模式仅排除裸 `auth`（避免误伤 `"authType":"oauth"` 之类的字面量字段）。
  - 行为变化：JSON `"authorization":"..."` / `"sess":"..."` / `"sid":"..."` 现在也会被脱敏（旧实现仅命中 8 个 key），属于覆盖面扩大。`tests/unit/test_redaction.py` 既有断言全部继续通过。

- **调试包临时文件残留清理**
  - 新增 `argus_py/infra/temp_cleanup.py`：定义 `DEBUG_BUNDLE_TMP_PREFIX = "argus-debug-"` 常量与 `cleanup_stale_debug_bundles(tmp_dir=None, *, prefix, min_age_seconds=60)`；扫描 `tempfile.gettempdir()` 中年龄超过阈值的同前缀 `*.zip` 并 `unlink`，所有 `OSError` 仅 `logger.warning`，确保启动流程不被脏文件阻断。
  - `argus_py/api/routes/events.py`：`download_debug_bundle` 创建 `NamedTemporaryFile` 时显式传 `prefix=DEBUG_BUNDLE_TMP_PREFIX`；从 `infra.temp_cleanup` 反向 import 该常量，保持 `infra` → `api` 单向依赖。
  - `argus_py/api/app.py`：在 `lifespan` 启动阶段调用 `cleanup_stale_debug_bundles()`，覆盖进程被强 kill / `os.unlink` 失败两类残留场景。

- **`httpx` proxy 配置开关**
  - `argus_py/llm/client.py`：`LLMClient.__init__` 新增 `httpx_proxy: str | None = None`、`httpx_trust_env: bool | None = None` 两个关键字参数；未显式传入时回落到环境变量 `LLM_HTTPX_PROXY` / `LLM_HTTPX_TRUST_ENV`（`"0" / "false" / "no" / "off"` 关闭 trust_env）。
  - `_ensure_http()` 创建 `httpx.AsyncClient` 时按 httpx 版本兼容地传代理：优先 `proxy=...`（httpx 0.28+），若 `TypeError` 回落 `proxies=...`（httpx <0.28，匹配项目最低依赖 0.27）。无显式 proxy 时不带 `proxy` 参数，仍由 `trust_env` 决定是否读取系统 `HTTP(S)_PROXY`。
  - 默认行为完全不变：6 个 `LLMClient(...)` 调用点均使用关键字参数，新增参数为关键字默认值，无需调整。

---

## Phase 3 · 长期（架构演进）

> 状态：3.4 已完成 ✅，其余 ⏳ 待办。

- 3.1 SQLite `schema_migrations` 版本号机制（替换裸 `executescript`）。
- 3.2 WebSocket 历史事件从 `task_events` 表回放，避免新连接错过早期事件。
- 3.3 进程内队列升级为 SQLite 持久化队列 + lease（重启不丢任务）。
- 3.4 ✅ 测试覆盖：`RecoveryPolicy` / `ActionExecutor` / `BlackboxExecutionLoop` / 路由契约 / 前端 vitest 全部补齐。
- 3.5 ✅ 静态检查：ruff + pre-commit + `eslint.config.js` 落地。
- 3.6 部署：Dockerfile + docker-compose + GitHub Actions（lint / test / build matrix）。

### 3.4 测试覆盖补齐细节

- **`tests/unit/test_recovery_policy.py`**：参数化覆盖 `RecoveryPolicy.decide` 决策矩阵 — 6 个 `_REPLAN_ERROR_CODES` 触发 `REPLAN`、未达 `max_attempts` 触发 `RETRY`、已达 `max_attempts` 触发 `ABORT`、无 `error_code` 走 `RETRY → ABORT`。
- **`tests/unit/test_action_executor.py`**：用 duck-typed `FakeBrowserSession` / `FakeBrowserActions`（不依赖 Playwright），覆盖：
  - `resolve_error_code` 对 `TaskError` / `BrowserTimeoutError` / `ElementNotFoundError` / 其它异常的映射。
  - 9 条 `dispatch_action` 校验路径：goto 缺 url / goto plain text / click / fill / press 缺 selector / press 缺 key / select 缺 selector / select 缺 value / 未注册的 action 类型。
  - `execute_action` happy path（追加 `SUCCESS` 日志 + 返回 observation）；`task.capture_screenshots=False` 时 `_screenshot` 跳过；失败路径写 `FAILED` 日志并抛 `TaskError` 携带映射后的 `error_code`。
  - `_step_params` 把 step 主字段与 `params` 字典合并为 JSON 安全的扁平 dict。
- **`tests/unit/test_execution_loop.py`**：用 `StubPlanner` / `StubEvaluator` / `StubActionExecutor` 完全控制 plan/evaluate/execute 三段，覆盖 7 条控制流：
  - 初始 plan 为空 → `规划器未返回可执行动作。`
  - 一次成功 + evaluator(completed, success) → `TaskStatus.COMPLETED` + `result_summary` 落库。
  - evaluator(completed=True, success=False) → 抛 `TaskError`。
  - `param_invalid` 错误码触发 `REPLAN`：`plan_next` 被调用 1 次、`last_error` 携带正确字段后再清空。
  - 普通错误码累计达 `max_attempts` → `ABORT` 抛 `TaskError`。
  - `max_steps` 用尽 → `_handle_max_steps` 把任务推至 `FAILED` 并抛 `TaskError`。
  - `check_cancelled_fn` 命中：`action_executor` / `plan_initial` 都不被调用，直接走 `Finalizer.finalize`。
- **`tests/unit/test_route_contracts.py`**：直接 `await` 调用路由函数（不启 ASGI），冻结 `TaskAppError → HTTPException` 的契约：
  - happy path：`POST /tasks` 创建 PENDING、`GET /tasks` 分页 + 状态过滤、`GET /tasks/infer-limits` 返回正数。
  - error code 契约 7 条：`TASK_NOT_PENDING`(409) / `TASK_NOT_RUNNING`(409) / `TASK_NOT_PAUSED`(409) / `TASK_ALREADY_FINISHED`(400) / `TASK_NOT_RETRYABLE`(409) / `TASK_NOT_EDITABLE`(409) / `TASK_NOT_DELETABLE`(409)。
  - 项目契约：`get_project` 不存在抛 `ProjectError`、`delete_project` 有关联任务抛 `ProjectError`。
- **前端 vitest 引入**：
  - `frontend/package.json`：新增 `test` / `test:watch` 脚本与 `vitest@^1.6.0` + `jsdom@^24.0.0` devDeps。
  - `frontend/vitest.config.ts`：独立配置（`environment: jsdom`、`include: src/**/*.{test,spec}.ts`），不污染 `vite.config.ts` 的 build/proxy。
  - `frontend/src/__tests__/utils.spec.ts`：覆盖 `formatDate` / `compact` / `taskDisplayStatus` / `canStartTask` / `canRestartTask` / `nullableText` / `nullableNumber` / `nullableBoolean` / `parseJsonObject` / `errorMessage` / `errorCode` / `upsertById` / `sortBy`。
  - `frontend/src/composables/__tests__/useDebounceFn.spec.ts`：用 `vi.useFakeTimers()` 验证延迟、合并、`cancel()` / `flush()`，并用 `effectScope().stop()` 断言 onScopeDispose 自动清理。

### 3.5 静态检查落地细节

- **后端 ruff**
  - `pyproject.toml` 新增 `[tool.ruff]` / `[tool.ruff.lint]` / `[tool.ruff.lint.per-file-ignores]` 三块配置；`line-length=100` 与 black 对齐，`target-version="py311"` 与项目最低版本对齐。
  - 规则集 `select = ["E", "W", "F", "B", "PT"]`：仅启用真正能抓 bug 的检查（pyflakes 未使用 import / pycodestyle 错误 / bugbear 模式 / pytest 风格），不启用 `I`（避免与现有 isort hook 重复）、`UP` / `SIM`（避免触发大量历史代码 diff）。
  - `ignore`：`E501` 行长度让 black 接管、`B008` 给 FastAPI `Depends()` / `Query()` 默认参数留行、`B904` 暂不强制 `raise X from exc`、`PT011` / `PT004` 给已有测试惯例留行。
  - `extend-exclude` 排除 `argus_py/api/static`（前端构建产物）、`frontend`（前端代码不进 Python lint）、`.venv` / `build` / `dist`。
  - 测试与脚本目录单独放宽：`tests/**` 允许 `E402` / `B011`，`scripts/**` 允许 `T201` 打印。
  - `[project.optional-dependencies].dev` 加 `ruff>=0.6,<1.0` 与 `pre-commit>=3.7`。
- **pre-commit**
  - `.pre-commit-config.yaml` 在 black / isort 之后插入 `ruff` local hook（`python -m ruff check --force-exclude`），保证格式化先行、ruff 只读检查、不会与 black 争夺空白。
  - mypy hook 顺序保持在 ruff 之后，让类型检查跑在 lint 修复之后。
- **前端 ESLint flat config**
  - 新建 `frontend/eslint.config.js`（ESM 数组式 flat config），合并 `js.configs.recommended` + `typescript-eslint.configs.recommended` + `vue.configs["flat/vue3-recommended"]`；`.vue` 文件用 `vue-eslint-parser` 包裹后内部委托给 `typescript-eslint` parser。
  - global ignores：`node_modules`、`dist`、`src/components.d.ts`（unplugin-vue-components 自动生成）、`../argus_py/api/static`（vite 构建产物）。
  - 复刻原 `.eslintrc.cjs` 的 3 条项目自定义规则：`@typescript-eslint/no-explicit-any: warn`、`vue/multi-word-component-names: off`、`vue/max-attributes-per-line: off`。
  - 测试文件 (`src/**/*.{spec,test}.ts`) 单独关掉 `no-explicit-any` / `no-non-null-assertion`，给 vitest 的 fake / mock helper 留行。
  - `frontend/.eslintrc.cjs` 删除（避免 ESLint 9 同时识别两份配置）。
  - `frontend/package.json` devDeps 调整：移除 `@typescript-eslint/eslint-plugin` / `@typescript-eslint/parser` / 旧 `eslint@^8.57`，新增 `eslint@^9.10`、`@eslint/js@^9.10`、`typescript-eslint@^8.5`、`vue-eslint-parser@^9.4.3`、`globals@^15.9`，保留 `eslint-plugin-vue@^9.27`（已支持 flat config）。
  - `lint` 脚本无需变更：`eslint --fix src/` 在 flat config 下沿用相同语义（路径作为 positional argument）。

---

## 变更记录

| 日期 | 项 | 摘要 |
| ---- | -- | ---- |
| 2026-05-13 | 1.1 | 前端按需加载 + 路由懒加载完成 |
| 2026-05-13 | 1.2 | `PRAGMA journal_mode` 移至 `init_database` |
| 2026-05-13 | 1.3 | reports / events 路由 `async def → def` 改为线程池执行 |
| 2026-05-13 | 1.4 | LLMClient 复用 `httpx.AsyncClient` 并在四个调用入口显式 `aclose()` |
| 2026-05-13 | 1.5 | trace JSONL 流式分页（`itertools.islice`）+ 损坏行跳过 + 同步化 9 个 events 单测 |
| 2026-05-14 | 2.1 | `_TaskResponseBase` + `_common_fields` 收敛 TaskResponse / TaskSummaryResponse 共享字段 |
| 2026-05-14 | 2.2 | `BrowserActions` 引入 `_handle_browser_errors` 装饰器，6 个方法去重异常处理 |
| 2026-05-14 | 2.3 | `infra/db.py` 加 `with_conn` / `with_tx` 上下文 helper，6 个 storage / repository 切换 |
| 2026-05-14 | 2.6 | 新增 `useDebounceFn` helper（自动 onScopeDispose 清理），`useTasks` / `useTaskList` / `useTaskEvents` 三处 setTimeout 模板替换 |
| 2026-05-14 | 2.7 | 脱敏关键词集中到 `redaction/patterns.py`、调试包加 `argus-debug-` 前缀并启动期清理残留、`LLMClient` 新增 `httpx_proxy` / `httpx_trust_env` 配置 |
| 2026-05-14 | 2.4 | 新增 `task/_base.py::_StorageEventBase` 收敛 `_resolve_task` / `_publish`；`task/event.py` 新增 `_NullTimelineService` Null Object，TaskService.timeline 不再为 None |
| 2026-05-14 | 2.5 | ReportView 抽出 `StepCard` / `FindingCard` / `reportUtils`，LLMDebugTab 抽出 `DebugCodeSection`，两文件分别从 1834/703 行降至 1303/569 行 |
| 2026-05-14 | 3.4 | 新增 4 个后端单测模块（recovery_policy / action_executor / execution_loop / route_contracts）+ 前端 vitest 落地（utils / useDebounceFn） |
| 2026-05-14 | 3.5 | 后端引入 ruff（与 black/isort 共存的纯 lint）+ pre-commit ruff hook；前端从 .eslintrc.cjs 迁到 ESLint 9 flat config (`eslint.config.js`)，typescript-eslint 升至 8.x |
| 2026-05-14 | 3.5 | 首次跑 ruff 清理 6 处遗留警告：路由 `test_model_config` 路由名 PT028 ignore；schemas `__all__` 补 `InferredLimitsResponse`；llm_trace lambda 显式绑定 pattern（B023）；`task_repo.zip(strict=True)`；`task/storage.py` lambda 改为内嵌 def；**修真实 bug**：`report.serializer` 的脱敏 `task_logs` 此前未写回 `data["task"]["logs"]`，JSON 报告 / 调试包会泄露原文 |
| 2026-05-14 | 3.5 | 首次跑 ESLint flat config 清理：`useTasks` / `ModelsView` 移除 2 个真未使用变量；`vue/no-mutating-props` 因 Element Plus 表单存量场景降为 warn 渐进迁移。**Lint 顺手发现 2 个待修问题**（不阻塞 3.5）：① `useConsoleApp.ts:46` `selectedTaskIdRef = taskDomain.selectedTaskId` 在 `connectEventStream` 已传出旧 ref 之后赋值，事件流永远拿不到选中任务变更（真 bug）；② `SidebarMenu.vue` / `TaskTable.vue` 各 1 个预先存在的 vue-tsc 类型错误（与 3.5 无关，需独立修） |
| 2026-05-14 | 3.5-fix | 修上面三处遗留：① `useConsoleApp` 改用普通对象 `{ current: Ref }` 当 holder（`shallowRef<Ref<X>>` 会被 vue-tsc auto-unwrap，行不通），`connectEventStream` 闭包始终读最新 inner ref；② `SidebarMenu.vue` 把内联 `$emit('changeView', $event)` 拆成 `onSelect(index: string)` 函数 + `as ViewKey` 显式收窄；③ `TaskTable.vue` `tagType` 返回类型从 `string` 收紧为 `"success" \| "info" \| "danger" \| "warning" \| "primary"` 字面量联合。`vue-tsc --noEmit` / `eslint .` 均回到 0 error |
