# Argus 优化路线图

> 落盘版本，跟踪短期 / 中期 / 长期优化项的执行进度。每完成一项，请更新对应条目的状态、最后修改日期，并在“变更记录”追加一行。

---

## 进度概览

| 阶段 | 主题 | 已完成 | 待完成 |
| ---- | ---- | ------ | ------ |
| Phase 1 | 短期：可立即收益的高价值改动 | 5 / 5 | — |
| Phase 2 | 中期：可维护性 / 代码结构 / 安全 | 0 / 7 | 全部 |
| Phase 3 | 长期：架构演进 / 工程基建 | 0 / 6 | 全部 |

最近更新：2026-05-13。

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

> 状态全部为 ⏳ 待办。

- 2.1 `TaskResponse` / `TaskSummaryResponse` 抽公共基类 + 收敛 `ConfigDict(populate_by_name=True)`。
- 2.2 `BrowserActions` 异常处理装饰器统一封装超时 / 元素未找到。
- 2.3 Repository 层引入 `_with_conn` / `_with_tx` 上下文 helper，去除重复 `connect()` + `closing` 模板。
- 2.4 `TaskService` facade 简化或拆分（按 lifecycle / query / events 分组）。
- 2.5 `ReportView.vue` / `LLMDebugTab.vue` 拆分子组件 + CSS 抽离。
- 2.6 `useTasks` debounce 抽 `useDebounceFn` helper。
- 2.7 安全细节收敛：脱敏字段集合常量化、调试包临时文件清理、httpx proxy 配置开关。

---

## Phase 3 · 长期（架构演进）

> 状态全部为 ⏳ 待办。

- 3.1 SQLite `schema_migrations` 版本号机制（替换裸 `executescript`）。
- 3.2 WebSocket 历史事件从 `task_events` 表回放，避免新连接错过早期事件。
- 3.3 进程内队列升级为 SQLite 持久化队列 + lease（重启不丢任务）。
- 3.4 测试覆盖：补 `execution_loop` / `action_executor` / 路由契约 / 前端 vitest。
- 3.5 静态检查：ruff + pre-commit + `eslint.config.js`。
- 3.6 部署：Dockerfile + docker-compose + GitHub Actions（lint / test / build matrix）。

---

## 变更记录

| 日期 | 项 | 摘要 |
| ---- | -- | ---- |
| 2026-05-13 | 1.1 | 前端按需加载 + 路由懒加载完成 |
| 2026-05-13 | 1.2 | `PRAGMA journal_mode` 移至 `init_database` |
| 2026-05-13 | 1.3 | reports / events 路由 `async def → def` 改为线程池执行 |
| 2026-05-13 | 1.4 | LLMClient 复用 `httpx.AsyncClient` 并在四个调用入口显式 `aclose()` |
| 2026-05-13 | 1.5 | trace JSONL 流式分页（`itertools.islice`）+ 损坏行跳过 + 同步化 9 个 events 单测 |
