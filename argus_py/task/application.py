"""任务应用服务层：编排 TaskService + TaskQueue + ProjectService + ModelConfigService。

HTTP 路由只做参数/响应转换，所有业务编排逻辑集中在此。
CLI 也可复用此类避免重复编排逻辑。
关联（CorrelationRun）的写操作编排位于 ``argus_py.correlation.application``；
本类仅保留以任务为中心的关联只读查询。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from argus_py.browser.url_validator import validate_url
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError, TaskRetryConflictError
from argus_py.correlation.presenters import (
    attempt_to_dict,
    correlation_run_to_dict,
    http_request_to_dict,
    summary_to_dict,
)
from argus_py.infra.queue import TaskQueue
from argus_py.observability.context import run_in_thread
from argus_py.project.service import ProjectService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.policies import (
    can_delete,
    can_edit,
    can_pause,
    can_resume,
    can_retry,
    can_start,
    is_terminal,
)
from argus_py.task.read import TaskReadService
from argus_py.task.strategy import resolve_execution_limits
from argus_py.utils.casing import camel_keys

# 任务队列满载时建议客户端等待后重试的秒数，作为 HTTP ``Retry-After`` 头返回。
QUEUE_FULL_RETRY_AFTER_SECONDS = 5


class TaskAppError(TaskError):
    """应用层业务规则错误，携带 HTTP 状态码和结构化详情以便路由层转换。"""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.http_status = http_status
        self.details = details or {}
        super().__init__(message)

    def to_http_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": camel_keys(self.details),
        }


class TaskApplicationService:
    """任务应用服务：合并项目默认值、校验状态机、协调队列。"""

    def __init__(
        self,
        lifecycle: TaskLifecycleService,
        task_read: TaskReadService,
        queue: TaskQueue,
        project_service: ProjectService,
        model_config_service: ModelConfigService,
    ) -> None:
        self._lifecycle = lifecycle
        self._read = task_read
        self._queue = queue
        self._project = project_service
        self._model_config = model_config_service
        # 重试链进程内锁：以源任务 ID 为键，避免同实例并发重试竞争；
        # 正确性由数据库 uq_tasks_retry_parent 部分唯一索引兜底（多实例场景）。
        self._restart_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ── 参数解析（合并项目默认值、模型配置校验、执行限制推断）──

    def resolve_create_params(
        self,
        goal: str,
        name: str | None = None,
        start_url: str | None = None,
        task_type: Any = None,
        project_id: str | None = None,
        max_steps: int | None = None,
        timeout_seconds: int | None = None,
        capture_screenshots: bool | None = None,
        model_config_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        whitebox_config: Any | None = None,
    ) -> dict[str, Any]:
        """解析任务参数：URL 校验 + 项目默认值合并 + 模型配置校验 + 执行限制推断。

        ``project_id`` 为 None 时跳过项目相关合并，纯参数校验后返回。
        """
        project = self._project.get_project(project_id) if project_id else None
        is_whitebox = task_type == TaskType.WHITEBOX

        if not is_whitebox:
            # ── 黑盒 ──
            start_url = start_url or (project.base_url if project else None)
            if not start_url:
                raise TaskError("任务需要 startUrl，或项目需要配置 baseUrl。")
            result = validate_url(start_url)
            if not result.is_ok():
                raise TaskError(f"startUrl 校验失败：{result.error_message}")

            # 项目默认执行限制先合并：用户显式值优先，其次项目默认，最后留给推断。
            # 必须在 resolve_execution_limits 之前合并，否则项目默认 max_steps/timeout
            # 会被 limits 计算时的 None 静默忽略（capture_screenshots 走局部变量返回值、
            # 不受影响，此前两处默认值是否生效不一致）。白盒不在此合并——白盒是单步
            # 分析，max_steps/timeout 固定兜底值，不继承项目浏览器默认限制。
            if project:
                max_steps = max_steps if max_steps is not None else project.default_max_steps
                timeout_seconds = (
                    timeout_seconds
                    if timeout_seconds is not None
                    else project.default_timeout_seconds
                )

            limits = resolve_execution_limits(goal, start_url, max_steps, timeout_seconds)
            whitebox_config_json: str | None = None
        else:
            # ── 白盒 ──
            from argus_py.task.strategy import TaskExecutionLimits
            from argus_py.whitebox.config import WhiteboxTaskConfig

            # 1. 提取原始输入
            if whitebox_config is not None:
                raw = whitebox_config.model_dump(exclude_unset=True)
            else:
                raw = dict(parameters or {})

            # 2. 项目默认值（仅 scope/target_modules/maven，不含源码位置）
            project_defaults: dict[str, Any] = {}
            if project:
                for key in ("scope", "target_modules", "maven"):
                    if key in project.parameters:
                        project_defaults[key] = project.parameters[key]

            # 3. maven 深度合并（仅当 raw["maven"] 为 dict 时才安全解包）
            if "maven" in project_defaults and "maven" in raw and isinstance(raw["maven"], dict):
                raw["maven"] = {**project_defaults["maven"], **raw["maven"]}
                del project_defaults["maven"]

            # 4. 合并 + 统一校验
            merged = {**project_defaults, **raw}
            config = WhiteboxTaskConfig.model_validate(merged)

            # 5. 持久化配置
            persisted = config.to_persisted()
            whitebox_config_json = persisted.model_dump_json()

            # 6. parameters 仅保留白盒执行参数，不含源码位置
            params: dict[str, Any] = {
                "scope": config.scope,
                "target_modules": config.target_modules,
            }
            if config.maven:
                params["maven"] = config.maven.model_dump(exclude_none=True)
            parameters = params

            limits = TaskExecutionLimits(
                max_steps=max_steps or 1,
                timeout_seconds=timeout_seconds or 3600,
            )

        if project:
            # max_steps/timeout 的项目默认值已在上方合并；此处只处理 capture_screenshots
            # 与 parameters 合并。
            capture_screenshots = (
                capture_screenshots
                if capture_screenshots is not None
                else project.default_capture_screenshots
            )
            merged_params = {**project.parameters, **(parameters or {})}
        else:
            merged_params = {**(parameters or {})}

        if model_config_id:
            self._model_config.get_model_config(model_config_id)
            merged_params["model_config_id"] = model_config_id

        return {
            "goal": goal,
            "name": name,
            "start_url": start_url,
            "task_type": task_type,
            "project_id": project.project_id if project else project_id,
            "max_steps": limits.max_steps,
            "timeout_seconds": limits.timeout_seconds,
            "capture_screenshots": capture_screenshots,
            "parameters": merged_params,
            **({"whitebox_config_json": whitebox_config_json} if whitebox_config_json else {}),
        }

    # ── 创建/更新 ──

    def create_task(self, **params: Any) -> Any:
        """创建任务快照。"""
        return self._lifecycle.create_task(**params)

    async def update_task(self, task_id: str, params: dict[str, Any]) -> Any:
        """更新 pending 且未入队的任务。"""
        # SQLite 读写都走线程池：协程中并发请求互不阻塞。
        task = await run_in_thread(self._read.get_task, task_id)
        scheduler_status = await self._queue.scheduler_status(task_id)
        if not can_edit(task.status) or scheduler_status is not None:
            raise TaskAppError(
                "TASK_NOT_EDITABLE",
                f"只有 pending 且未入队的任务可以编辑，当前状态：{task.status.value}。",
                details={
                    "task_id": task_id,
                    "status": task.status.value,
                    "scheduler_status": scheduler_status,
                },
            )
        updated = await run_in_thread(self._lifecycle.update_task_info, task, **params)
        return updated, await self._queue.scheduler_status(updated.task_id)

    # ── 删除 ──

    async def delete_task(self, task_id: str) -> None:
        """删除 pending 且未入队的任务。"""
        task = await run_in_thread(self._read.get_task, task_id)
        scheduler_status = await self._queue.scheduler_status(task_id)
        if not can_delete(task.status) or scheduler_status is not None:
            raise TaskAppError(
                "TASK_NOT_DELETABLE",
                f"只有 pending 且未入队的任务可以删除，当前状态：{task.status.value}。",
                details={
                    "task_id": task_id,
                    "status": task.status.value,
                    "scheduler_status": scheduler_status,
                },
            )
        await run_in_thread(self._lifecycle.delete_pending_task, task)

    # ── 启动 ──

    async def start_task(self, task_id: str) -> tuple[Any, str]:
        """将 pending 任务加入执行队列。"""
        task = await run_in_thread(self._read.get_task, task_id)
        if not can_start(task.status):
            raise TaskAppError(
                "TASK_NOT_PENDING",
                f"只有 pending 任务可以启动，当前状态：{task.status.value}。",
                details={"task_id": task.task_id, "status": task.status.value},
            )
        result = await self._queue.try_enqueue(task.task_id)
        if result.rejected:
            raise await self._queue_full_error(task.task_id)
        if result.already_known:
            raise TaskAppError(
                "TASK_ALREADY_SCHEDULED",
                f"任务已处于调度状态：{result.scheduler_status}。",
                details={"task_id": task.task_id, "scheduler_status": result.scheduler_status},
            )
        return task, result.scheduler_status

    async def _queue_full_error(self, task_id: str) -> TaskAppError:
        """构造队列满载错误（503 + Retry-After），附带容量/排队诊断。"""
        qm = await self._queue.metrics()
        return TaskAppError(
            "TASK_QUEUE_FULL",
            "任务队列已满，请稍后重试。",
            http_status=503,
            details={
                "task_id": task_id,
                "retry_after_seconds": QUEUE_FULL_RETRY_AFTER_SECONDS,
                "capacity": qm["capacity"],
                "queued": qm["queued"],
            },
        )

    # ── 重试 ──

    async def restart_task(self, task_id: str) -> tuple[Any, str]:
        """重试失败/超时/取消的任务，创建新任务并立即入队。

        重试链保持线性：同一源任务在任一时刻最多一个直接重试子任务。
        进程内 asyncio.Lock 负责同实例并发去重并给出友好错误；数据库
        ``uq_tasks_retry_parent`` 部分唯一索引负责跨实例兜底。
        """
        # 锁外快速失败（非终态），避免为显然不可重试的任务占锁。
        task = await run_in_thread(self._read.get_task, task_id)
        if not can_retry(task.status):
            raise TaskAppError(
                "TASK_NOT_RETRYABLE",
                f"只有失败/超时/取消的任务可以重试，当前状态：{task.status.value}。",
                details={"task_id": task.task_id, "status": task.status.value},
            )
        lock = self._restart_locks[task_id]
        try:
            async with lock:
                # 锁内重新读取并做完整校验：任务状态可能在等待期间变化；子任务
                # 检查必须与创建处于同一临界区。锁需覆盖持久化（restart_task
                # 内部已 save），保证子任务先落库再释放锁。
                resolved = await run_in_thread(self._read.get_task, task_id)
                if not can_retry(resolved.status):
                    raise TaskAppError(
                        "TASK_NOT_RETRYABLE",
                        f"只有失败/超时/取消的任务可以重试，当前状态：{resolved.status.value}。",
                        details={"task_id": resolved.task_id, "status": resolved.status.value},
                    )
                if await run_in_thread(self._lifecycle.has_retry_child, task_id):
                    raise TaskAppError(
                        "TASK_ALREADY_RETRIED",
                        "该任务已有重试任务，请重试最新一次。",
                        details={"task_id": task_id},
                    )
                try:
                    new_task = await run_in_thread(self._lifecycle.restart_task, resolved)
                except TaskRetryConflictError as exc:
                    # 跨实例/绕过锁的并发写入被唯一索引拦下
                    raise TaskAppError(
                        "TASK_ALREADY_RETRIED",
                        "该任务已有重试任务，请重试最新一次。",
                        details={"task_id": task_id},
                    ) from exc
        finally:
            # 清理锁表，避免随重试次数无限增长。等待中的协程持有锁对象引用，
            # 删除字典项不影响它们继续等待；极端并发下第二个请求可能短暂拿到
            # 新锁，由数据库唯一索引兜底拒绝。
            if self._restart_locks.get(task_id) is lock:
                self._restart_locks.pop(task_id, None)
        # 锁已释放、子任务已持久化后才入队；入队失败回滚删除子任务，
        # 父任务随之重新获得重试资格（删除语义规则 B）。
        try:
            result = await self._queue.try_enqueue(new_task.task_id)
        except (Exception, asyncio.CancelledError):
            # try_enqueue 内部 put_nowait 不会抛 QueueFull（满载走 rejected），
            # 但可能因协程取消或其它异常终止。无论哪种异常，new_task 已写入
            # DB，必须回滚。
            await run_in_thread(self._lifecycle.delete_pending_task, new_task)
            raise
        if result.rejected:
            # 队列满载：回滚刚创建的 retry 子任务，父任务恢复重试资格，
            # 客户端可稍后重试 restart。
            await run_in_thread(self._lifecycle.delete_pending_task, new_task)
            raise await self._queue_full_error(task_id)
        if result.already_known:
            await run_in_thread(self._lifecycle.delete_pending_task, new_task)
            raise TaskAppError(
                "TASK_ALREADY_SCHEDULED",
                f"新创建的任务意外处于已调度状态：{result.scheduler_status}。",
                details={"task_id": new_task.task_id, "scheduler_status": result.scheduler_status},
            )
        return new_task, result.scheduler_status

    # ── 取消失败/已终态校验 ──

    async def _check_not_finished(self, task_id: str) -> tuple[Any, str | None]:
        """获取任务并校验未处于终态。返回 (task, scheduler_status)。"""
        task = await run_in_thread(self._read.get_task, task_id)
        scheduler_status = await self._queue.scheduler_status(task_id)
        if is_terminal(task.status):
            raise TaskAppError(
                "TASK_ALREADY_FINISHED",
                f"任务已处于终态，不能操作：{task.status.value}。",
                http_status=400,
                details={"task_id": task_id, "status": task.status.value},
            )
        return task, scheduler_status

    async def cancel_task(self, task_id: str) -> tuple[Any, str | None]:
        """取消任务。pending/queued 从队列移除；running 通过信号量中断。"""
        task, scheduler_status = await self._check_not_finished(task_id)
        if scheduler_status == "queued":
            await self._queue.cancel(task_id)
        # CancellationToken 线程不安全；必须在 event loop 线程修改信号量，
        # 否则线程池写入与执行循环读取形成不可观测的 data race。
        self._lifecycle.get_cancellation_token(task.task_id).cancel()
        task = await run_in_thread(self._lifecycle.cancel_task, task)
        return task, await self._queue.scheduler_status(task.task_id)

    # ── 暂停/恢复 ──

    async def pause_task(self, task_id: str) -> Any:
        task = await run_in_thread(self._read.get_task, task_id)
        if not can_pause(task.status):
            raise TaskAppError(
                "TASK_NOT_RUNNING",
                f"只有运行中的任务可以暂停，当前状态：{task.status.value}。",
                details={"task_id": task.task_id, "status": task.status.value},
            )
        # CancellationToken 线程不安全；必须在 event loop 线程修改信号量。
        self._lifecycle.get_cancellation_token(task.task_id).pause()
        return await run_in_thread(self._lifecycle.pause_task, task)

    async def resume_task(self, task_id: str) -> Any:
        task = await run_in_thread(self._read.get_task, task_id)
        if not can_resume(task.status):
            raise TaskAppError(
                "TASK_NOT_PAUSED",
                f"只有暂停的任务可以恢复，当前状态：{task.status.value}。",
                details={"task_id": task.task_id, "status": task.status.value},
            )
        # CancellationToken 线程不安全；必须在 event loop 线程修改信号量。
        self._lifecycle.get_cancellation_token(task.task_id).resume()
        return await run_in_thread(self._lifecycle.resume_task, task)

    # ── 查询（委托） ──

    async def get_task_with_scheduler(self, task_id: str) -> tuple[Any, str | None]:
        task = await run_in_thread(self._read.get_task, task_id)
        sched = await self._queue.scheduler_status(task_id)
        return task, sched

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        task_type: TaskType | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Any], int]:
        return self._read.list_task_summaries(
            status=status,
            project_id=project_id,
            task_type=task_type,
            offset=offset,
            limit=limit,
            q=q,
        )

    async def snapshot_queue_statuses(self) -> dict[str, str]:
        return await self._queue.snapshot_statuses()

    def get_dashboard_stats(self, recent_limit: int = 8) -> dict[str, Any]:
        """返回仪表盘聚合统计：全量计数与最近任务摘要。

        - tasks_total / running_total：跨页准确（COUNT 走 SQLite 索引）
        - findings_total：当前所有任务的发现项数量
        - recent_tasks：按 created_at 降序的前 ``recent_limit`` 条 task summary

        ``list_task_summaries`` 内部用 ``COUNT(*) OVER()`` 窗口函数同 SQL 返回
        全表 total，所以这里直接复用，省掉一次额外的 ``count_tasks()`` 全表扫描。
        """
        running_total = self._read.count_tasks(status=TaskStatus.RUNNING)
        findings_total = self._read.count_findings()
        recent, tasks_total = self._read.list_task_summaries(offset=0, limit=recent_limit)
        return {
            "tasks_total": tasks_total,
            "running_total": running_total,
            "findings_total": findings_total,
            "recent_tasks": recent,
        }

    # ── 分析执行查询（阶段二）──────────────────────────────────

    def list_analysis_runs(
        self, task_id: str, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Any], int]:
        """列出任务的所有分析执行记录。"""
        return self._read.storage.list_analysis_runs(task_id, offset=offset, limit=limit)

    def get_latest_analysis_run(self, task_id: str) -> Any:
        """获取任务的最近一次分析执行。"""
        return self._read.storage.get_latest_analysis_run(task_id)

    def get_analysis_run(self, analysis_id: str) -> Any:
        """按 ID 获取分析执行详情。"""
        return self._read.storage.get_analysis_run(analysis_id)

    def list_analysis_endpoints(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._read.storage.list_analysis_endpoints(analysis_id, cursor=cursor, limit=limit)

    def list_analysis_call_nodes(
        self,
        analysis_id: str,
        *,
        class_name: str | None = None,
        method_name: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._read.storage.list_analysis_call_nodes(
            analysis_id,
            class_name=class_name,
            method_name=method_name,
            cursor=cursor,
            limit=limit,
        )

    def list_analysis_call_edges(
        self,
        analysis_id: str,
        *,
        entry_node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._read.storage.list_analysis_call_edges(
            analysis_id,
            entry_node_id=entry_node_id,
            cursor=cursor,
            limit=limit,
        )

    def list_analysis_execution_flows(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        return self._read.storage.list_analysis_execution_flows(
            analysis_id, cursor=cursor, limit=limit
        )

    def list_analysis_clusters(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[Any], str | None, int | None, bool]:
        return self._read.storage.list_analysis_clusters(analysis_id, cursor=cursor, limit=limit)

    def get_analysis_diagnostics(self, analysis_id: str) -> dict[str, Any] | None:
        return self._read.storage.get_analysis_diagnostics(analysis_id)

    def get_analysis_counts(self, analysis_id: str) -> dict[str, int]:
        return self._read.storage.get_analysis_counts(analysis_id)

    def get_analysis_counts_batch(self, analysis_ids: list[str]) -> dict[str, dict[str, int]]:
        """批量返回多个分析的投影计数（analysis-runs 列表用，消除 N+1 COUNT）。"""
        return self._read.storage.get_analysis_counts_batch(analysis_ids)

    def get_analysis_finding_severity_counts(self, analysis_id: str) -> dict[str, int]:
        return self._read.storage.get_analysis_finding_severity_counts(analysis_id)

    def get_analysis_finding_severity_counts_batch(
        self, analysis_ids: list[str]
    ) -> dict[str, dict[str, int]]:
        """批量返回多个分析的 findings 严重级别分布（analysis-runs 列表用）。"""
        return self._read.storage.get_analysis_finding_severity_counts_batch(analysis_ids)

    def list_all_analysis_flow_steps(self, analysis_id: str) -> list[dict[str, Any]]:
        """一次查询返回分析的全部执行流步骤（执行流列表路由用，消除 N+1）。"""
        return self._read.storage.list_all_analysis_flow_steps(analysis_id)

    def list_analysis_flow_steps_for_flows(
        self, execution_flow_ids: list[str]
    ) -> list[dict[str, Any]]:
        """按 execution_flow_id 集合批量返回 flow steps（执行流分页路由用）。"""
        return self._read.storage.list_analysis_flow_steps_for_flows(execution_flow_ids)

    def get_analysis_findings(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[Any], str | None, int | None, bool]:
        return self._read.storage.get_analysis_findings(analysis_id, cursor=cursor, limit=limit)

    # ── 关联只读查询（CorrelationRun / Evidence）────────────────

    def list_correlation_runs_by_task(self, task_id: str) -> list[dict[str, Any]]:
        """通过 taskId 查找所有关联运行。

        支持黑盒任务 ID（BlackboxRun.task_id → CorrelationRun）
        和白盒任务 ID（AnalysisRun.task_id → analysis_id → CorrelationRun）。
        """
        storage = self._read.storage
        seen: set[str] = set()
        result: list[dict[str, Any]] = []

        # 路径 1：黑盒任务 → BlackboxRun → CorrelationRun（批量，消除 N+1）
        bb_runs = storage.list_blackbox_runs_by_task(task_id)
        if bb_runs:
            bb_ids = [bb.blackbox_run_id for bb in bb_runs]
            for cr in storage.list_correlation_runs_by_blackbox_run_ids(bb_ids):
                if cr.correlation_run_id not in seen:
                    seen.add(cr.correlation_run_id)
                    result.append(correlation_run_to_dict(cr))

        # 路径 2：白盒任务 → AnalysisRun → CorrelationRun
        # 全量取分析运行（无固定上限），避免多次重分析后部分关联运行静默丢失。
        analysis_runs = storage.list_all_analysis_runs(task_id)
        if analysis_runs:
            analysis_ids = [a.analysis_id for a in analysis_runs]
            if analysis_ids:
                wb_crs = storage.list_correlation_runs_by_analysis_ids(analysis_ids)
                for cr in wb_crs:
                    if cr.correlation_run_id not in seen:
                        seen.add(cr.correlation_run_id)
                        result.append(correlation_run_to_dict(cr))

        return result

    def get_correlation_run(self, correlation_run_id: str) -> dict[str, Any] | None:
        cr = self._read.storage.get_correlation_run(correlation_run_id)
        if cr is None:
            return None
        return correlation_run_to_dict(cr)

    def list_correlation_attempts(self, correlation_run_id: str) -> list[dict[str, Any]]:
        attempts = self._read.storage.list_correlation_attempts_by_run(correlation_run_id)
        return [attempt_to_dict(a) for a in attempts]

    def get_correlation_attempt(
        self, correlation_run_id: str, attempt_id: str
    ) -> dict[str, Any] | None:
        attempt = self._read.storage.get_correlation_attempt(attempt_id)
        if attempt is None:
            return None
        # 归属校验：Attempt 必须属于指定的 CorrelationRun
        if attempt.correlation_run_id != correlation_run_id:
            return None
        return attempt_to_dict(attempt)

    def get_correlation_summary(self, correlation_run_id: str) -> dict[str, Any]:
        summary = self._read.storage.get_correlation_summary(correlation_run_id)
        return summary_to_dict(summary)

    def build_correlation_report_data(self, analysis_id: str) -> dict[str, Any] | None:
        """构建白盒任务文件型报告的关联数据（跨运行聚合，camelCase）。

        实现位于 ``argus_py.correlation.report_data``；此方法保留供既有调用方
        以任务服务为入口复用。
        """
        from argus_py.correlation.report_data import (
            build_correlation_report_data as _build,
        )

        return _build(self._read.storage, analysis_id)

    def list_endpoint_evidence(
        self,
        correlation_run_id: str,
        *,
        resolution_status: str | None = None,
        match_strategy: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        storage = self._read.storage
        cr = storage.get_correlation_run(correlation_run_id)
        if cr is None or cr.active_attempt_id is None:
            return [], 0
        items, total = storage.list_endpoint_evidence(
            cr.active_attempt_id,
            resolution_status=resolution_status,
            match_strategy=match_strategy,
            offset=offset,
            limit=limit,
        )

        if not items:
            return [], total

        # ── 组装 matchedEndpointInfo / candidates / executionFlows ──
        matched_ids = [it["matched_endpoint_id"] for it in items if it.get("matched_endpoint_id")]
        evidence_ids = [it["endpoint_evidence_id"] for it in items]

        ep_map: dict[str, dict[str, Any]] = {}
        candidates_map: dict[str, list[dict[str, Any]]] = {}
        flows_map: dict[str, list[dict[str, Any]]] = {}

        if matched_ids:
            ep_map = storage.batch_get_endpoint_details(matched_ids)
        if evidence_ids:
            candidates_map = storage.batch_get_candidates(evidence_ids)
            flows_map = storage.batch_get_flows(evidence_ids)

        for it in items:
            ep_id = it.get("matched_endpoint_id")
            if ep_id and ep_id in ep_map:
                ep = ep_map[ep_id]
                it["matched_endpoint_info"] = {
                    "endpointId": ep.get("endpoint_id", ""),
                    "endpointFingerprint": ep.get("endpoint_fingerprint", ""),
                    "analysisId": ep.get("analysis_id", ""),
                    "sourceSnapshotId": ep.get("source_snapshot_id"),
                    "httpMethod": ep.get("http_method", ""),
                    "normalizedPath": ep.get("normalized_exact_path")
                    or ep.get("normalized_path_template", ""),
                    "normalizedPathTemplate": ep.get("normalized_path_template", ""),
                    "isTemplated": bool(ep.get("is_templated")),
                    "pathSegmentCount": ep.get("path_segment_count", 0),
                    "controllerClass": ep.get("controller_class"),
                    "controllerMethod": ep.get("controller_method"),
                    "parameters": [],
                    "returnType": ep.get("return_type"),
                }
            else:
                it["matched_endpoint_info"] = None

            eid = it["endpoint_evidence_id"]
            it["candidates"] = candidates_map.get(eid, [])
            it["execution_flows"] = flows_map.get(eid, [])

        return items, total

    def list_unmatched_requests(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        storage = self._read.storage
        items, total = storage.list_unmatched_requests(
            correlation_run_id,
            offset=offset,
            limit=limit,
        )
        return [http_request_to_dict(r) for r in items], total

    def list_finding_evidence(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        storage = self._read.storage
        items, total = storage.list_finding_evidence(
            correlation_run_id,
            offset=offset,
            limit=limit,
        )

        if not items:
            return [], total

        # ── 组装 findingInfo ──
        finding_ids = [it["finding_id"] for it in items]
        finding_map = storage.batch_get_finding_details(finding_ids)

        for it in items:
            fid = it.get("finding_id", "")
            f = finding_map.get(fid)
            if f:
                it["finding_info"] = {
                    "findingId": f.get("finding_id", ""),
                    "title": f.get("title", ""),
                    "description": f.get("description", ""),
                    "severity": f.get("severity", ""),
                    "findingType": f.get("finding_type", ""),
                    "location": f.get("location"),
                    "ruleId": f.get("rule_id"),
                    "ruleCategory": f.get("rule_category"),
                    "confidence": f.get("confidence"),
                    "snippet": f.get("snippet"),
                    "analysisId": f.get("analysis_id"),
                    "createdAt": f.get("created_at", ""),
                }
            else:
                it["finding_info"] = None

        return items, total

    def get_capture_quality(self, blackbox_run_id: str) -> dict[str, Any] | None:
        return self._read.storage.get_capture_quality(blackbox_run_id)

    def list_uncovered_endpoints(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._read.storage.list_uncovered_endpoints(
            correlation_run_id,
            offset=offset,
            limit=limit,
        )
