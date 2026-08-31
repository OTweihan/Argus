# Argus 剩余优化审查（2026-08-10）

## 1. 审查结论

本次审查以 `docs/architecture.md` 为架构基线，并对照
本审查排除了此前已经完成的事项。当前代码已经具备较好的
分层、SQLite 批量查询、Java 有界线程池、EventBus 背压、OpenAPI 门禁和跨服务契约测试基础。
下一阶段不宜继续以“拆大文件”或“引入更多框架”为主要目标，更高收益的方向是：

1. 让单进程、队列容量、就绪探针和网络边界真正做到 fail-closed；
2. 补齐 Python 取消后 Java 作业仍继续运行、WebSocket 回放缺口等失效语义；
3. 消除源码快照与指纹的重复全量 I/O，并给大型分析结果设置真实内存预算；
4. 修复异步请求乱序和 handler 返回值丢失等容易在边界条件下暴露的正确性问题；
5. 对大规模投影写入做基准驱动的批量化，再推进 Java 分析管线的类型化边界。

O-01～O-11 已于 2026-08-10～08-11 按此建议全部实施完成（见 §3 完成标记与各节完成说明）；P2 项
O-10/O-11 已分别以压测/查询计划与新增分析 pass 架构门禁需求落地，后续优化以新增分析 pass 等实际需求
作为触发条件。

## 2. 审查范围与方法

审查范围：

- Python API、运行时容器、任务队列、Worker、TaskRunner、EventBus、白盒 Runner；
- SQLite task/analysis/correlation repository 与迁移索引；
- Vue 任务列表、运行时事件和 WebSocket 客户端；
- Java Analyzer 作业、缓存、源码定位、分析编排与线程池；
- Docker Compose、Dockerfile、健康检查和 CI；
- 现有单元、集成、契约与 E2E 测试覆盖。

审查方式：先通过仓库 `.codegraph/` 索引检查符号和调用路径，再阅读相关源码、配置、迁移与测试。
本次只新增本文档，未修改业务代码，未运行构建或测试。

优先级定义：

| 优先级 | 含义 |
|---|---|
| P0 | 可能破坏安全边界、单实例一致性或部署探针语义，应优先收敛 |
| P1 | 明确的可靠性、正确性或显著资源收益，建议进入最近迭代 |
| P2 | 需要基准或规模触发的性能/架构演进，不应无数据提前重构 |

## 3. 优化项总览

| ID | 优先级 | 优化项 | 主要收益 |
|---|---|---|---|
| O-01 | P0 | 默认部署入口与源码路径边界改为 fail-closed | 降低未鉴权访问、路径探测和任意可见目录分析风险（✅ 已完成） |
| O-02 | P0 | 强制单 Python 实例，并修正 readiness/Worker 存活语义 | 防止多进程状态分裂，避免探针把失效实例判为可用（✅ 已完成） |
| O-03 | P0 | 为任务提交增加有界、非阻塞的准入控制 | 防止任务无限堆积和 HTTP 请求长时间挂起（✅ 已完成） |
| O-04 | P1 | 实现 Java 作业协作取消与服务端 deadline | 取消/超时后及时释放线程、Maven 进程与源码快照（✅ 已完成） |
| O-05 | P1 | 显式处理 EventBus 回放缺口和服务重启 epoch | 避免断线后任务终态长期停留在旧值（✅ 已完成） |
| O-06 | P1 | TaskRunner 使用 handler 返回的 Task | 消除返回新快照时的结果、报告或终态信息丢失风险（✅ 已完成） |
| O-07 | P1 | 合并源码快照、内容指纹与 Java 缓存键计算 | 降低大型仓库冷启动 I/O、磁盘占用和重复哈希（✅ 已完成） |
| O-08 | P1 | Java 分析缓存按权重限制，而非只限制条目数 | 控制大型调用图缓存造成的堆内存峰值（✅ 已完成） |
| O-09 | P1 | 前端列表与参数推断增加请求代次/取消 | 防止旧响应覆盖新筛选条件或新输入（✅ 已完成） |
| O-10 | P2 | 批量化分析投影写入，修正游标分页重复计数 | 降低大型分析结果的 SQLite 调用开销（✅ 已完成） |
| O-11 | P2 | 收敛 Java DTO/核心边界并引入类型化 AnalysisPass | 降低新增分析能力时的编排分支和跨层耦合（✅ 已完成） |

## 4. 详细优化建议

### O-01 默认部署入口与源码路径边界改为 fail-closed（P0）

> ✅ **已完成并补强（2026-08-10）**。默认 Compose 仅回环暴露 Python、Java 仅
> expose；非回环 CLI 启动要求至少 32 字符且非占位值的 Token，内网 Compose 覆盖
> 使用必填环境变量。Java 容器固定 `/tmp/sources`，裸机默认临时快照根目录；
> `validate-source` 对 allowed-root 外、逃逸及不存在路径统一返回全 false，避免路径探测。
> 浏览器使用短时单次 WS ticket，长期 Token query 已移除，仅允许 Bearer 头。

**现状证据**

- `argus_py/api/app.py:147-150` 仅在 `ARGUS_API_TOKEN` 非空时启用鉴权；未配置时 API 默认开放。
- `docker-compose.yml` 将 Python `8000` 和 Java `8081` 都映射到宿主机，示例没有强制配置 API
  Token，也没有为 Java Analyzer 配置服务间认证。
- `java_analyzer/.../support/SourceLocator.java:16-27` 只做绝对路径归一化、存在性和目录校验，
  没有 allowed roots 或 `toRealPath()` 后的边界校验。
- `AnalysisController.validateSource()` 直接调用 `Files.exists/isReadable`，没有复用 `SourceLocator`。
  可直接访问 Java 端口的调用方可以探测路径，并要求 Analyzer 分析 Java 进程可见的任意目录。
- 浏览器 WebSocket 当前通过 `?token=` 传递长期 Token（`frontend/src/ws.ts:63-68`、
  `argus_py/api/auth.py:91-113`），查询串可能进入反向代理或接入日志。

**建议方案**

1. Compose 默认只将 Python 绑定到 `127.0.0.1`，或在非回环监听时要求显式提供
   `ARGUS_API_TOKEN`/反向代理认证；为确需内网开放的场景提供单独部署覆盖文件。
2. Java Analyzer 默认只 `expose` 给 Compose 内部网络，不映射宿主机端口。本地独立调试通过明确的
   dev override 开放端口。
3. Java 增加 `argus.analysis.allowed-source-roots`，容器固定为 `/tmp/sources`。`analyze` 与
   `validate-source` 统一经过同一个 real-path 校验器，并拒绝符号链接逃逸。
4. 跨主机部署时为 Python→Java 增加最小服务凭据或 mTLS，不把 Analyzer 当作可信公网接口。
5. 浏览器先用 Bearer HTTP 请求换取短时、单次 WebSocket ticket，或由受保护反代使用安全 Cookie；
   不把长期 API Token 放入 WebSocket URL。

**兼容与迁移风险**

- 默认端口可见性变化会影响直接访问 `:8081` 的本地脚本，应先提供 dev override 和迁移说明。
- Python 本地源码输入未配置 roots 时仍保留兼容告警；Java 和容器分析边界已 fail-closed。
- 旧客户端若通过 WS query 传长期 Token 将被拒绝，必须切换到 ticket 或 Bearer 头。

**验收标准**

- 未鉴权客户端不能读取或修改任务数据，不能直接提交 Java 分析。
- `/etc`、宿主挂载目录、allowed roots 外路径及符号链接逃逸均被拒绝。
- 代理访问日志、应用访问日志和浏览器地址记录中不出现长期 Token。

### O-02 强制单 Python 实例，并修正 readiness/Worker 存活语义（P0）

> ✅ **已完成（2026-08-10）**。单实例 OS 文件锁、多 worker 拒启、lifespan 容器状态、
> Worker loop 健康快照和 readiness 503 已落地并由定向测试覆盖。

**现状证据**

- `argus_py/api/app.py:54-77` 的 `_warn_if_multi_worker()` 发现多 worker 时只记录 ERROR，不拒绝启动；
  直接运行 `uvicorn ... --workers N` 仍可绕过 CLI 护栏。
- `tests/unit/test_serve_worker_guard.py` 明确把 lifespan 行为固定为“仅告警”。这与架构基线中的
  单进程硬约束仍有差距。
- `/ready` 在依赖未就绪时返回 `status="not_ready"`，但 HTTP 状态仍是 200；
  `tests/unit/test_api_contract_asgi.py:157-165` 也固化了该行为。标准探针通常只看状态码，因此会继续
  向未就绪实例导流。
- `TaskWorker.is_started` 只返回布尔标志；即使 Worker loop 已异常结束，readiness 和 `/metrics` 的
  `worker_alive` 仍可能为真。
- readiness 的 EventBus 检查只是判断 getter 返回值非空，不能证明事件派发任务正常。

**建议方案**

1. 在 lifespan 启动时获取基于 DB/outputs 的跨进程独占锁；获取失败直接拒绝启动。OS 文件锁应随进程
   退出自动释放，避免使用无法可靠回收的普通 pid 文件。
2. 对可识别的 `WEB_CONCURRENCY`/`UVICORN_WORKERS > 1` 直接抛启动错误，文件锁作为无法识别启动方式
   时的最终防线。
3. `TaskWorker` 暴露真实健康快照：Worker task 总数、存活数、异常结束数和最近一次消费时间；为 loop
   增加 done callback，记录未处理异常。
4. `/ready` 未就绪时返回 HTTP 503；`/health` 继续只表示进程存活，不执行昂贵依赖检查。
5. readiness 不应通过 getter 隐式创建依赖，应检查 lifespan 已成功初始化的容器状态。

**兼容与迁移风险**

- 依赖 `/ready` 的脚本若错误地期待 200，需要同步修正；这属于探针语义纠正。
- Windows 与 Linux 文件锁实现不同，应封装为小型基础设施 adapter，并分别测试锁竞争和异常退出。

**验收标准**

- 两个进程指向同一 DB/outputs 时只有一个能进入 ready。
- Worker loop 全部异常结束后 `/ready` 返回 503，`/health` 仍可用于存活诊断。
- Compose/Kubernetes 能根据 503 停止导流，并在依赖恢复后重新 ready。

### O-03 为任务提交增加有界、非阻塞的准入控制（P0）

> ✅ **已完成（2026-08-10）**。实现要点：
> - `TaskQueue.try_enqueue()` 在锁内原子完成去重 + `put_nowait`，满载立即 `rejected=True` 且不残留
>   `_queued_ids`；`_queued_ids` 改为 `dict[str, float]`（task_id → 入队时刻）支撑 oldest age 指标。
> - 默认容量 0 → 32（`DEFAULT_QUEUE_MAX_SIZE`），`config/server.yaml` 同步并给出估算注释；
>   `argus serve` 对 `queue_max_size=0`（无界）打告警。
> - `start/restart` 改走 `try_enqueue`；满载抛 `TASK_QUEUE_FULL`（HTTP 503 + `Retry-After`），
>   `restart` 满载回滚已创建的 retry 子任务。`_to_http_exception` 透传 `Retry-After`；
>   middleware `handle_http_error` 合并 `HTTPException.headers`（修复此前丢弃自定义响应头的隐患）。
> - `/metrics` 增加 `queue_capacity / queue_utilization / queue_oldest_queued_age_seconds /
>   queue_rejected_total`；前端 `overloadMessage()` 对过载类错误提示"稍后重试"。
> - 容量估算公式（已修订）：`queue_max_size ≈ concurrency × 允许等待时间 ÷ 平均任务时长`。

**现状证据**

- `config/server.yaml:19-22` 的 `scheduler.queue_max_size` 默认是 `0`，即 `asyncio.Queue` 无界。
- `TaskQueue` 同时维护 `_queued_ids`，持续提交会同时增长队列和集合。
- 若运维把队列改为有限容量，`TaskQueue.enqueue()` 使用 `await self._queue.put(task_id)`；队列满时 API
  请求会等待空位，而不是快速返回明确的过载响应。
- 默认限流关闭，因此限流不能替代系统级队列容量。

**建议方案**

1. 给出保守的有限默认容量，并允许按部署资源调整；容量为 0 仅作为显式开发选项。
2. 增加原子的 `try_enqueue()`：在锁内完成重复检查和 `put_nowait`，满载时不把 task_id 留在
   `_queued_ids`。
3. API 将满载映射为稳定错误码（如 `TASK_QUEUE_FULL`）和 HTTP 429/503，并返回 `Retry-After`；
   不让请求无限等待。
4. 指标增加 capacity、utilization、oldest queued age、rejected total，而不仅是 queued/active 数量。
5. 对 start/restart 的幂等语义增加“队列满、客户端重试、任务已在队列”组合测试。

**兼容与迁移风险**

- 以前能无限排队的调用方会收到显式过载错误；前端应提示稍后重试，而不是把它显示为一般失败。
- 容量不能仅凭经验设定，应结合平均任务时长和允许等待时间给出部署计算说明。

**验收标准**

- 并发提交超过容量时，内存和请求延迟保持有界，超额请求快速失败。
- 重试不会导致同一 task_id 重复执行，队列指标与内部集合始终一致。

### O-04 实现 Java 作业协作取消与服务端 deadline（P1）

> ✅ **已完成并补强（2026-08-10）**。Java 侧 `AnalysisJobService` 重写为单向 CAS 状态机：
> `markRunning/Succeeded/Failed/Cancelled/TimedOut` 全部 CAS，取消/完成/超时并发先发生者定序；
> `getResult` 仅在 SUCCEEDED 返回，取消后不可发布结果。新增幂等 `cancel(jobId)`（PENDING 直接落
> CANCELLED 并从执行队列移除，`future.cancel(false)` 不 interrupt；RUNNING 置协作令牌 + 经
> `MavenProcessRegistry` 立即终止 Maven 进程树；已终态 no-op），Controller 新增
> `DELETE /argus/api/analyze/jobs/{jobId}`；`enforceDeadlines()` @Scheduled 对运行/排队作业兜底
> TIMED_OUT（PENDING 同时取消排队 Future，避免执行器随后再启动分析）。协作检查下钻到
> `SourceFileScanner`/`ControllerExtractor`/`CallGraphBuilder`/`FindingDetector`/`ExecutionFlowTracer`/
> `CommunityClusterer`/`ModuleClassifier`/`MavenExecutor`，统一抛 `JobCancelledException`（非
> ClasspathException 子类，不被 gateway 吞掉）；`runJob` 捕获 `CompletionException` 解包取消信号。
> Python 侧 `WhiteboxClient.cancel_analyze_job`（DELETE，404→None）；`WhiteboxRunner` 取消先
> `_cancel_remote_with_confirmation`（确认窗口内轮询 CANCELLED）→ confirmed 落 CANCELLED /
> requested|unknown|unreachable 保留 STOPPED_WAITING；超时与 Worker shutdown（asyncio.CancelledError
> → shield）均 best-effort 通知远端。新增 `whitebox/recovery.py`：
> `reconcile_orphan_whitebox_jobs` 对孤儿作业按远端状态重新接管/拉结果/落超时/落失败，`TaskWorker`
> 可选持有 whitebox_client 完整接管。Python 1322 tests 全过；Java 侧经本次 `mvn test`（2026-08-12）
> BUILD SUCCESS——147 tests，0 failures / 0 errors，2 skipped（均在 `SourceLocatorTest`，Windows 下
> symlink 相关用例跳过），含 `AnalysisJobServiceTest` 13 个取消/超时/CAS 用例与 ArchUnit
> `DependencyRuleTest`。已知边界：同一 cacheKey 下 job B 被
> 去重到 job A 的 in-flight future 时，A 取消会让 B 的 `join()` 抛 `CompletionException` 并按取消
> 处理（单 worker 每源单分析下罕见，若需 B 重跑可后续观察）。

**现状证据**

- `argus_py/whitebox/runner.py:460-474` 明确说明本地取消只停止轮询，Java 作业可能仍在运行。
- Python 超时同样不会通知 Java；源码快照只能保留并等待 24 小时 TTL 回收。
- `AnalysisJobService.runJob()` 直接执行分析，没有保存 `Future`、取消令牌或服务端 deadline。
- Java 状态模型已预留 `CANCELLED/TIMED_OUT` 消费分支，但当前服务端不能真正产生协作取消终态。

**建议方案**

1. 新增幂等取消接口，例如 `DELETE /argus/api/analyze/jobs/{jobId}`。
2. JobStore 保存 `Future`/取消令牌；分析 pass、文件扫描和聚类在安全边界检查令牌。
3. Maven 外部进程单独持有 `ProcessHandle`，取消或 deadline 到达时终止进程树并关闭输出读取任务。
4. 请求携带受服务端上限约束的 deadline/timeout，防止 Python 断联后作业永久占用资源。
5. Python 在用户取消、任务超时和 Worker shutdown 时 best-effort 调用远端取消；只有 Java 确认后才落
   `CANCELLED`，无法确认时保留现有 `STOPPED_WAITING` 语义。
6. 启动恢复时检查保存的 `external_job_id`：按既定产品语义选择重新接管、获取已完成结果，或主动取消，
   不再静默遗留孤儿作业。

**兼容与迁移风险**

- JavaParser 计算不能在任意位置安全强杀，应采用协作检查；Maven 进程则必须处理子进程树。
- 取消与完成可能并发，需要用单向 CAS 状态机定义“完成先发生”与“取消先发生”的确定结果。

**验收标准**

- 用户取消或 Python deadline 到达后，Java 工作线程和 Maven 进程在约定时间内释放。
- 重复取消返回同一终态；取消成功后不能再发布成功结果。
- Python 不可达、Java 重启和取消/完成竞态均有契约测试。

### O-05 显式处理 EventBus 回放缺口和服务重启 epoch（P1）

> ✅ **已完成（2026-08-10）**。实现要点：
> - `EventBus` 新增 `stream_epoch`（进程级纪元，重启即变化）与 `ReplayWindow`/`EventSubscriptionResult`；
>   `subscribe_with_replay()` 把回放收集为有界列表（不经过比 history 更小的订阅队列，避免 drop-oldest），
>   `replay_window()` 返回可回放窗口。
> - `ws.py`：`system.ready` 携带 `streamEpoch/oldestSequence/currentSequence/replayComplete`；
>   `system.replay_gap`（`epoch_changed`/`since_seq_out_of_window`）显式下发、不静默丢事件；回放按
>   `REPLAY_BATCH_SIZE=100` 分批直发；`_stream_events` 重构为 select 循环，断连时主动释放订阅队列。
> - 前端 `ws.ts`：`TaskEventStream` 消费 `system.ready`（纪元变化兜底触发 gap）与 `system.replay_gap`
>   （清空 `lastSequence` + 防重复上报）；重连带 `epoch` query，指数退避 + 50%–100% jitter。
>   `useRuntimeEvents.onReplayGap`；`useConsoleApp` gap 处理器触发 `refreshRuntimeData()` +
>   `timelineReloadTick++`，`TaskTimeline` 重拉持久化时间线。顺序正确性依据：DB 写入先于 publish →
>   SQLite 快照恒 ≥ 已接收事件，权威刷新代次防乱序。
> - 测试：`test_event_bus.py`（subscribe_with_replay/stream_epoch）、`test_ws_utils.py`（ready/gap 事件）、
>   新 `tests/integration/test_ws_replay_gap.py`；前端 `ws.spec.ts`/`useTaskEvents.spec.ts`/`clientAuth.spec.ts`。
>   Python 1345 + 前端 192 tests 全过。

**现状证据**

- EventBus 默认 history 为 200，但每个订阅队列默认只有 100；`subscribe(replay=True)` 通过 `_offer()`
  回放，回放量超过队列容量时会直接 drop-oldest。
- 服务端只让客户端看到 sequence 跳号，没有返回“最早可回放 sequence”或明确的 gap 事件。
- sequence 在进程重启后从 0 开始，客户端 `TaskEventStream.lastSequence` 没有服务端 epoch/run_id；客户端
  可能用重启前的高 sequence 请求新进程回放，从而跳过新进程已积累的历史。
- `useConsoleApp.ts` 在 `reconnected` 时只刷新 dashboard stats，没有刷新当前任务或任务列表。

**建议方案**

1. `system.ready` 返回 `streamEpoch`、`oldestSequence`、`currentSequence` 和 `replayComplete`。
2. 当 `sinceSeq` 早于可回放窗口、epoch 变化或 replay 队列不足时发送 `system.replay_gap`，不要静默丢失。
3. 前端遇到 gap/epoch 变化时清空旧 cursor，并从 SQLite API 刷新当前任务、可见列表和持久化时间线；
   WebSocket 继续只作为低延迟通知。
4. 回放阶段可直接生成有界批次发送，避免先塞入比 history 更小的订阅队列。
5. 重连退避增加 jitter，减少多个控制台在服务恢复瞬间同时重连。

**兼容与迁移风险**

- 新 system 字段和事件类型可向后兼容新增；旧前端会忽略未知事件，但升级窗口内服务端仍应保持原行为。
- authoritative refresh 要避免与实时 patch 乱序，可复用 O-09 的请求代次机制。

**验收标准**

- 覆盖 `history_limit > subscriber_queue_size`、超出回放窗口、服务重启 sequence 重置和端点切换测试。
- 断线期间发生的任务终态最终与 SQLite 一致，不依赖用户手动刷新页面。

### O-06 TaskRunner 使用 handler 返回的 Task（P1）

> ✅ **已完成（2026-08-10）**。实现要点：
> - `TaskRunner.run()` 保存 `handler_result = await asyncio.wait_for(...)` 并传入
>   `_finalize_run(running_task, handler_result)`。
> - `_finalize_run` 完成前读取最新持久化状态：已写入终态（外部取消/并发终态）或非 RUNNING
>   （外部 pause）时原样返回、绝不覆盖；报告生成后再核对一次，防止迟到的成功返回覆盖外部取消。
> - handler 返回全新 Task 快照时以其为结果数据源，生命周期/身份字段从最新持久化状态回填
>   （`_LIFECYCLE_FIELDS`）；返回 None 或原地返回同一对象时以运行期 task 对象为准（Whitebox 现状保持）。
> - `TaskHandler` 收窄为 async-only，同步 handler 被拦截并给出明确错误（须经 `run_in_thread` 包装）。
>   运行时行为变更：同步 handler 抛 `TypeError` 并落 FAILED（旧实现会透传返回值正常完成）；当前生产
>   handler（blackbox/whitebox 均为 async）不受影响。
> - 新增 `tests/unit/test_task_runner.py`：返回全新快照 / 返回 None / 并发取消 / 已写终态 /
>   外部 pause / 同步 handler 拒绝，6 个用例。

**现状证据**

- `TaskRunner.run()` 在 `asyncio.wait_for()` 中等待 `_run_handler()`，但没有保存返回值。
- `_finalize_run(task, result=None)` 已经设计了 `result` 参数，却从未接收到 handler result。
- `BlackboxRunner.run()` 返回 `Task`，而 `WhiteboxRunner.run()` 返回 `None`。当前测试中的简单 handler 多数
  原地修改同一对象，因而没有覆盖“handler 返回新的 Task 快照”的情况。

**建议方案**

1. 保存 `handler_result = await asyncio.wait_for(...)`，并传入 `_finalize_run(running_task, handler_result)`。
2. 在完成前仍通过生命周期 CAS/最新状态检查防止覆盖外部 cancel/pause；不要把“使用返回值”等同于无条件
   覆盖持久化终态。
3. 当前生产 handler 都是 async，可把 `TaskHandler` 收窄为 async-only；若确需同步扩展，则必须经统一
   `run_in_thread`，避免阻塞事件循环。
4. 增加 handler 返回全新 Task、返回 None、并发取消和已写终态四类回归测试。

**兼容与迁移风险**

- 低。主要风险是暴露现有 handler 对返回对象和持久化快照语义不一致的问题，应通过测试明确优先级。

**验收标准**

- handler 返回的新 `result_summary`、findings 和其他字段能进入报告与最终持久化结果。
- Whitebox 的 None 返回路径保持现状，外部取消不能被迟到的成功返回覆盖。

### O-07 合并源码快照、内容指纹与 Java 缓存键计算（P1）

> ✅ **已完成（2026-08-11）**。实现要点：
> - Python→Java 契约新增兼容字段 `sourceRevision`/`snapshotDigest`：Git 源传 commit SHA，
>   本地源传快照内容 SHA-256；`WhiteboxClient.submit_analyze_job/analyze` 与
>   `WhiteboxRunner._submit_job` 均透传。
> - `ProjectIndexCache.createKey` 在客户端提供 revision 时以
>   `revision + Maven 配置指纹 + analyzer/pass 版本` 建键，路径不再参与身份（跨快照目录可命中），
>   且查找不再全量读取源码树；旧客户端（无 revision）保留 path + 全量指纹回退。
> - `SourceResolver` 复制与内容指纹合并为单次流式遍历（`_materialize_snapshot`），不再复制后二次读取；
>   快照排除规则保守、可配置（默认排除 VCS/构建输出/工具缓存，不排除 `.mvn`/wrapper）。
>   注意：默认排除 `build/`（Gradle 构建输出）会改变 Gradle 项目的快照内容——Java 侧
>   `SourceFileScanner` 只过滤 `target/` 不过滤 `build/`，旧路径会扫描 `build/` 下生成的源码，
>   新路径因快照已排除而静默缺失。分析器以 Maven 为主，该差异风险低；如需分析 Gradle 生成源码，
>   可通过 `whitebox.snapshot_exclude_dirs` 放开。
> - 指标：Python 记录快照文件数/复制字节/复制与指纹耗时/排除目录数（`/metrics` 新增 `snapshot_*`），
>   Java `ProjectIndexCache.metrics()` 记录 lookup/hit/fingerprint/revision 统计。
> - reflink/hardlink 未引入：与流式哈希互斥且平台差异大，先以指标决定是否继续。

**现状证据**

- `SourceResolver._copy_snapshot()` 只固定忽略 `.git`，大型仓库的 `target`、`node_modules`、`.gradle`、
  IDE 缓存等也会被复制。
- 本地快照复制完成后，`_compute_dir_hash()` 再次读取快照中的全部文件。
- Java `ProjectIndexCache.createKey()` 在每次缓存查询前再次遍历源码树并读取所有 Java/构建文件计算
  SHA-256；因此“缓存命中”仍是 O(相关源码总字节数)。
- Git 源已经有 commit SHA，本地源也已经生成内容 SHA，但这些稳定 revision 没有进入 Python→Java 契约。

**建议方案**

1. 定义兼容新增字段 `sourceRevision`/`snapshotDigest`，由 Python 在物化不可变快照时计算一次并传给 Java。
2. Java 缓存键使用 revision + Maven 配置指纹 + analyzer/pass 版本；旧客户端未传 revision 时保留现有
   全量哈希回退。
3. 把复制和哈希合并为单次流式遍历；评估支持时使用 reflink/hardlink，但必须保持任务快照不可变。
4. 增加保守、可配置的排除规则，默认排除确定无关的 VCS、构建输出和工具缓存；`.mvn`、wrapper、
   可能参与生成源码的目录不得未经验证排除。
5. 指标记录 snapshot 文件数、复制字节、复制耗时、指纹耗时和 Java cache lookup 耗时，用数据决定是否
   继续引入增量 per-file digest。

**兼容与迁移风险**

- 排除目录可能改变包含生成源码的项目结果，必须按 Maven 多模块、generated sources 和 wrapper 场景测试。
- revision 由内部 Python 控制面提供；若未来允许第三方直接调用 Java，应决定是否信任或抽样校验。

**验收标准**

- 在同一大型仓库上，缓存命中不再全量读取源码内容。
- 冷分析的复制字节和目录占用显著下降，分析结果与旧路径保持契约一致。

### O-08 Java 分析缓存按权重限制，而非只限制条目数（P1）

> ✅ **已完成（2026-08-11）**。实现要点：
> - 新增 `ResponseWeightEstimator`：基于字符串长度（保守按 UTF-16 2 字节/字符）加固定
>   对象头/集合槽位开销估算 `AnalyzeResponse` 近似保留堆字节，零分配、O(响应元素数)。
> - `ProjectIndexCache` 同时约束 `maxEntries`、`maxTotalWeight` 与 `maxSingleEntryWeight`
>   （默认 128 / 64 MiB / 16 MiB，`argus.analysis.cache.*-weight-bytes` 可配）：超大响应
>   直接不缓存（oversized bypass），超出总权重预算按 LRU 淘汰，TTL 过期同步回收权重。
> - 缓存值插入时对顶层集合做浅拷贝 + 不可变包装，避免调用方修改共享响应污染后续请求；
>   可变类 `AnalyzerDiagnostics` 做全字段防御拷贝（内部集合同样不可变包装），
>   `put()` 返回 boolean 标识是否真正入缓存（超大旁路时 false）；
>   single-flight、异常传播与 TTL/LRU 语义保持不变。
> - `metrics()` 新增 current weight / current entries / eviction reason（count、weight、
>   expiry 分项）/ oversized bypass / in-flight 等指标。
> - 默认预算需用真实大型项目 + 受限 `-Xmx` 压测后调优（估算偏差只影响命中率）。

**现状证据**

- `ProjectIndexCache` 的 LRU 只限制 `maxEntries=128` 和 TTL。
- 单个 `AnalyzeResponse` 包含 endpoints、完整 call graph、findings、flows、clusters 和 diagnostics；不同项目
  响应大小可能相差数个数量级。
- 128 个大型调用图与 128 个小项目使用同一配额，条目上限不能形成可靠的堆内存上限。

**建议方案**

1. 先用节点数、边数、flow step 数或序列化估算字节建立近似权重，不要求第一版引入第三方缓存框架。
2. 同时配置 max entries、max total weight 和 max single-entry weight；超大响应直接不缓存。
3. 暴露 current weight、hit/miss、eviction reason、oversized bypass、in-flight 数和 fingerprint 耗时。
4. 缓存值尽量不可变，避免调用方修改共享响应导致后续请求读到污染数据。
5. 用真实大型项目和受限 `-Xmx` 做压力测试后再确定默认预算。

**兼容与迁移风险**

- 估算偏差只影响命中率，不应影响结果正确性；默认预算过小会增加重复分析，需要用指标调优。

**验收标准**

- 缓存压力下堆占用保持在配置预算附近，超大项目不会挤压到 OOM。
- single-flight 行为、异常传播和 TTL/LRU 语义保持不变。

### O-09 前端列表与参数推断增加请求代次/取消（P1）

> ✅ **已完成（2026-08-10）**。实现要点：
> - `api/task/index.ts`：`listTasks`/`inferTaskLimits` 增加可选 `options: { signal?: AbortSignal }`；
>   `client.request` 支持外部 signal（abort 统一转 `ApiError(code="REQUEST_ABORTED")`）；
>   `utils.isAbortError` 区分"正常取消"与真实失败，避免误弹错误 toast。
> - `useTaskList`：每次 `loadTasks` 先 abort 旧请求 + `++loadGeneration` 代次守卫——只有最新代次可写回
>   `allTasks/total/loading/error`；查询条件在发起瞬间定格为不可变快照（请求期间不再读 ref）；
>   `onScopeDispose` 置 disposed 并 abort。
> - `useTasks.autoFillLimits`：推断请求同样 abort + 代次守卫，响应落地前二次核对
>   `goal/startUrl/taskType/editingId` 均未变才写回，用户手工修改后不被自动推断覆盖。
> - 测试：`useTaskList.spec.ts`（11 用例：反序完成/快速切页/快速筛选/卸载/失败/取消等）、
>   `useTasks.spec.ts` 增补 autoFillLimits 取消与乱序防护（8 用例）。前端 212 tests 全过；
>   无 Python/Java 改动。

**现状证据**

- `useTaskList.loadTasks()` 没有 AbortController 或 request generation。筛选、分页、搜索和重连刷新可同时
  发起请求，较慢的旧请求可能最后返回并覆盖新条件的结果。
- 任一请求完成都会把 `taskLoading=false`，即使更新的请求仍在进行。
- `useTasks.autoFillLimits()` 同样可能让旧 goal/startUrl 的推断结果覆盖用户更新后的输入。
- `useTaskList` 没有直接测试；现有 `useTaskEvents` 测试主要覆盖事件合并策略。

**建议方案**

1. API adapter 支持 `AbortSignal`；每次新查询取消旧查询，并用递增 generation 防御无法取消的迟到响应。
2. 只有当前 generation 可以写入 `allTasks/total/loading/error`。
3. 列表查询参数形成不可变 snapshot，避免请求期间读取变化中的 ref。
4. auto-fill 在响应落地前再次核对 goal、startUrl、taskType 和 editingId；用户手工修改字段后不应被自动
   推断覆盖。
5. 增加 deferred promise 反序完成、快速切页、快速筛选、组件卸载和请求失败组合测试。

**兼容与迁移风险**

- 低。需要统一识别浏览器 abort error，避免把正常取消显示为错误 toast。

**验收标准**

- 无论请求返回顺序如何，页面只展示最后一次查询条件对应的数据。
- loading 状态准确，已取消请求不产生错误提示或覆盖用户输入。

### O-10 批量化分析投影写入，修正游标分页重复计数（P2）

> ✅ **已完成（2026-08-11）**。实现要点：
> - `_write_projection` 将 call nodes / endpoints / edges / flows / steps / clusters 由逐行
>   `conn.execute()` 改为同事务分批 `executemany`（`_executemany_batched`，默认单批 500）。
>   行源为生成器，由 `itertools.islice` 逐批取出，峰值内存只保留当前批、不随总行数增长。
>   事务边界保持在 `complete_projection` 的 `tx()` 内，任一批失败整体回滚，不暴露半份投影。
> - `_paginated_query` 仅在首页（无有效 cursor）执行 `COUNT(*)`；后续 cursor 页返回
>   `total=None`，由客户端复用首屏 total。OpenAPI 的 `total` 字段本已是 `int | None`，
>   前端 `usePagedList` 以 `page.total ?? null` 消费，无 schema / 前端变更。游标解码前置并
>   校验为与排序列等长的标量列表（非列表 / 键数不符 / 元素非标量如 bool、null、容器
>   均回退首页），不抛 500。
> - 新增 `tests/unit/test_analysis_projection_repo.py`：分批 chunk 边界、生成器行源分片、
>   6 张表走 executemany / 诊断单行 execute、中途失败回滚、重复投影幂等替换、
>   1137 行跨 3 批全量落库、cursor 分页第二页起不执行 COUNT（trace 断言）且无重复/无遗漏、
>   末页恰好填满、带筛选条件翻页、无效及结构非法游标（非列表 / 键数不符 /
>   元素非标量）回退首页。共 20 个用例。
> - 未新增索引：`EXPLAIN QUERY PLAN` 显示各分页查询已用 `analysis_id` 索引做过滤、
>   COUNT 走覆盖索引，仅 ORDER BY 需临时 B-tree；按审计结论不凭感觉加索引引入写放大。

**现状证据**

- `AnalysisRunRepository.replace_projection()` 已使用单事务保证原子性，但 call nodes、endpoints、edges、
  flows、steps 和 clusters 仍逐行 `conn.execute()`。
- `_paginated_query()` 的注释写“仅在首屏请求时计算 total”，实现却在每次有 cursor 的后续页仍执行
  `COUNT(*)`。
- 当前已有较好的批量读取和 SQLite 参数分片实践，可复用到投影写入。

**建议方案**

1. 先建立 1k/10k/50k nodes+edges 的投影基准，确认 Python↔SQLite 调用开销占比。
2. 将各表 row mapper 先构造为迭代器/分片列表，再在同一事务内使用 `executemany`；单批建议 200～1000，
   由基准决定。
3. 后续 cursor 页不重复计算 total，返回 `null` 或复用客户端首屏 total，并同步 OpenAPI 语义。
4. 对排序/过滤 SQL 运行 `EXPLAIN QUERY PLAN` 后再增加复合索引，避免凭感觉堆索引增加写放大。
5. 增加中途失败回滚、重复投影、超大批次和分页无重复/无遗漏测试。

**兼容与迁移风险**

- `executemany` 可能增加单批内存，必须分片；事务边界不能拆散，否则失败时会暴露半份投影。
- total 变为可选属于 API 语义调整，应使用兼容新增/已有可选字段并同步前端生成类型。

**验收标准**

- 大型投影写入耗时明显下降，结果行数、外键和原子可见性与现实现一致。
- 第二页及后续页不再执行全表/索引 COUNT，游标分页无重复和遗漏。

### O-11 收敛 Java DTO/核心边界并引入类型化 AnalysisPass（P2）

> ✅ **已完成并补强（2026-08-11）**。HTTP adapter 已将 wire DTO 映射为内部
> `AnalysisCommand`/`AnalysisResult`，五类分析能力统一实现 `AnalysisPass`，并由
> `PlanRegistry`/`PlanValidator` 校验能力重复、缺失与循环。`PassExecutor` 按依赖分波并行，
> 可选失败通过 `passFailures` 显式降级；同波任务在作业返回前全部收敛（含被有界执行器
> 拒绝的部分提交），JVM `Error` 原样传播并在 `AnalysisJobService` 作业边界落 `FAILED`
> 终态，不静默降级也不停在 `RUNNING` 等 deadline 兜底。
> ArchUnit 门禁禁止 domain/application 依赖 HTTP DTO、Spring 或具体 Maven gateway，
> 同时阻止分析 pass 反向依赖 HTTP DTO。

**现状证据**

- `ProjectAnalyzerService` 直接接收 `api.dto.AnalyzeRequest` 并构造 `AnalyzeResponse`。
- 核心流程仍比较 `"all"`、`"flows"`、`"clusters"` 等字符串 scope。
- Controller、call graph、diagnostics 和分析编排共享 HTTP DTO；`ProjectAnalyzerService` 固定编排多个
  future，并持有较多具体分析依赖。
- 这与 `docs/architecture.md` 已定义的 typed `AnalysisPlan/Capability`、纯 Java domain/application 和
  `AnalysisPass` 演进目标存在剩余差距。

**建议方案**

1. 先在 HTTP adapter 把 `AnalyzeRequest` 映射为内部不可变 `AnalysisCommand/AnalysisPlan`，核心不再读取
   HTTP DTO 或字符串 scope。
2. 把 endpoints、call graph、findings、flows、clusters 逐步包装为声明输入/输出 capability 的 pass；
   只有无依赖 pass 并行。
3. HTTP adapter 最后把内部 result 映射为 wire DTO，诊断中的可选 pass 失败按架构约定显式降级。
4. 增加包依赖测试，阻止 domain/application 依赖 Spring MVC、`api.dto` 和具体 Maven gateway。
5. 不要立即拆 Maven 子模块；等包边界稳定并出现独立构建需求后再评估。

**触发条件**

- 新增下一类分析能力或现有固定 future 编排再次增加条件分支时启动；若近期没有新增 pass，可保持 P2。

**验收标准**

- 核心分析单测无需 Spring Context；HTTP DTO 变化不直接传播到算法类。
- capability 依赖可在启动时校验重复、缺失和循环，分析结果顺序可重复。

## 5. 实施顺序（已全部完成）

> ✅ 以下批次已按计划全部实施完成（截至 2026-08-11）：第一批 O-01～O-03（安全与运行护栏）、
> 第二批 O-04～O-06 与 O-09（生命周期正确性）、第三批 O-07/O-08/O-10（基准驱动性能），
> O-11（类型化 AnalysisPass 与包依赖门禁）也已按扩展需求触发落地。

```text
第一批：安全与运行护栏
O-01 网络/路径 fail-closed
  ├─ O-02 单实例锁 + readiness 503
  └─ O-03 有界非阻塞队列

第二批：生命周期正确性
O-04 Java 协作取消/deadline
O-05 EventBus gap/epoch 恢复
O-06 TaskRunner 返回值闭环
O-09 前端请求代次与取消

第三批：基准驱动性能
O-07 快照/指纹单次计算
  └─ O-08 加权缓存预算
O-10 SQLite 批量投影与分页计数

按扩展需求触发
O-11 类型化 AnalysisPass 与包依赖门禁
```

依赖关系说明：

- O-04 完成后，Python 才能在取消/超时后安全释放源码快照；它应先于进一步缩短快照 TTL。
- O-05 的 authoritative refresh 应复用 O-09 的请求代次，避免 REST 恢复与实时事件互相覆盖。
- O-07 提供稳定 revision 后，O-08 的缓存键和缓存命中成本才真正可控。
- O-10 必须先基准和查询计划，不建议直接增加 SQLite 索引。

## 6. 建议补充的验证矩阵

| 场景 | 最低验证 |
|---|---|
| 多进程误启动 | 两进程竞争同一实例锁，第二个拒启；异常退出后锁可恢复 |
| readiness | DB 不可用、Worker loop 崩溃、容器未初始化时返回 503 |
| 队列满载 | 并发提交、重复 task_id、客户端取消、restart 重试和 shutdown |
| Java 取消 | PENDING/RUNNING/刚完成/重复取消/Maven 子进程/Java 重启 |
| EventBus 恢复 | history 溢出、订阅队列溢出、服务 epoch 变化、终态事件断线 |
| TaskRunner | handler 返回新 Task、None、已终态 Task、取消与迟到成功竞态 |
| 源码快照 | Git、本地脏仓、多模块、generated sources、symlink、超大缓存目录 |
| Java 缓存 | 超大单项、并发同 key、并发不同 key、TTL、加权淘汰、受限 Xmx |
| 前端请求 | 旧请求后返回、abort、快速筛选/翻页、重连刷新并发 |
| SQLite 投影 | 1k/10k/50k 规模、失败回滚、分页无重复和查询计划 |

> ✅ 上述场景均已由 O-01～O-11 对应的定向测试覆盖（详见各节"已完成"说明）；后续新增功能继续沿用该
> 矩阵作为回归基线。

## 7. 当前不建议做的事项

1. **不因队列问题直接引入 Redis/Kafka。** 当前产品仍是单进程/单副本，先把本地队列准入、取消和探针
   语义做正确；只有确定要多副本时再按架构基线整体迁移队列、EventBus、租约和存储。
2. **不因 repository 文件较大就立即换 ORM。** 当前主要瓶颈候选是投影逐行写入和重复 COUNT，可在现有
   SQLite adapter 内低风险解决。
3. **不立即拆 Java Maven 多模块或替换 Spring Boot。** 先通过内部 command/result、AnalysisPass 和包
   依赖测试稳定边界。
4. **不先增加更多线程。** Java 已有作业/内部分析独立有界执行器；取消、内存预算和准入比继续调高并发
   更重要。
5. **不把 WebSocket 升级为持久事实源。** 任务和时间线的恢复继续以 SQLite API 为准，EventBus 只负责
   低延迟通知。

## 8. 最终建议

上述最小高收益闭环已按建议完成：O-01～O-03 先落地，保证系统在错误部署和压力下能够拒绝而不是失控；
随后 O-04～O-06 与 O-09 把取消、断线恢复和任务终态做成可验证的一致语义；最后以大型仓库与调用图
基准完成 O-07、O-08、O-10，并把 O-11 作为新增分析能力前的架构门禁落地。后续优化应以压测、查询
计划或新增分析 pass 的实际需求作为触发条件，不提前重构。
