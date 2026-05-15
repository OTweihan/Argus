"""任务应用服务层：编排 TaskService + TaskQueue + ProjectService + ModelConfigService。

HTTP 路由只做参数/响应转换，所有业务编排逻辑集中在此。
CLI 也可复用此类避免重复编排逻辑。
"""

from __future__ import annotations

import asyncio
from typing import Any

from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus
from argus_py.core.exceptions import TaskError
from argus_py.infra.queue import TaskQueue
from argus_py.project.service import ProjectService
from argus_py.task.service import TaskService
from argus_py.task.strategy import resolve_execution_limits


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
            "details": self.details,
        }


class TaskApplicationService:
    """任务应用服务：合并项目默认值、校验状态机、协调队列。"""

    def __init__(
        self,
        task_service: TaskService,
        queue: TaskQueue,
        project_service: ProjectService,
        model_config_service: ModelConfigService,
    ) -> None:
        self._task = task_service
        self._queue = queue
        self._project = project_service
        self._model_config = model_config_service

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
    ) -> dict[str, Any]:
        """解析任务参数，合并项目默认值、校验模型配置、推断执行限制。"""
        project = self._project.get_project(project_id or "")
        start_url = start_url or project.base_url
        if not start_url:
            raise TaskError("任务需要 startUrl，或项目需要配置 baseUrl。")

        max_steps = max_steps or project.default_max_steps
        timeout_seconds = timeout_seconds or project.default_timeout_seconds
        capture_screenshots = (
            capture_screenshots
            if capture_screenshots is not None
            else project.default_capture_screenshots
        )
        merged_params = {**project.parameters, **(parameters or {})}
        if model_config_id:
            self._model_config.get_model_config(model_config_id)
            merged_params["modelConfigId"] = model_config_id

        limits = resolve_execution_limits(goal, start_url, max_steps, timeout_seconds)

        return {
            "goal": goal,
            "name": name,
            "start_url": start_url,
            "task_type": task_type,
            "project_id": project.project_id,
            "max_steps": limits.max_steps,
            "timeout_seconds": limits.timeout_seconds,
            "capture_screenshots": capture_screenshots,
            "parameters": merged_params,
        }

    # ── 创建/更新 ──

    def create_task(self, **params: Any) -> Any:
        """创建任务快照。"""
        return self._task.create_task(**params)

    async def update_task(self, task_id: str, params: dict[str, Any]) -> Any:
        """更新 pending 且未入队的任务。"""
        # SQLite 读写都走线程池：协程中并发请求互不阻塞。
        task = await asyncio.to_thread(self._task.get_task, task_id)
        scheduler_status = await self._queue.scheduler_status(task_id)
        if task.status is not TaskStatus.PENDING or scheduler_status is not None:
            raise TaskAppError(
                "TASK_NOT_EDITABLE",
                f"只有 pending 且未入队的任务可以编辑，当前状态：{task.status.value}。",
                details={
                    "taskId": task_id,
                    "status": task.status.value,
                    "schedulerStatus": scheduler_status,
                },
            )
        updated = await asyncio.to_thread(self._task.update_task_info, task, **params)
        return updated, await self._queue.scheduler_status(updated.task_id)

    # ── 删除 ──

    async def delete_task(self, task_id: str) -> None:
        """删除 pending 且未入队的任务。"""
        task = await asyncio.to_thread(self._task.get_task, task_id)
        scheduler_status = await self._queue.scheduler_status(task_id)
        if task.status is not TaskStatus.PENDING or scheduler_status is not None:
            raise TaskAppError(
                "TASK_NOT_DELETABLE",
                f"只有 pending 且未入队的任务可以删除，当前状态：{task.status.value}。",
                details={
                    "taskId": task_id,
                    "status": task.status.value,
                    "schedulerStatus": scheduler_status,
                },
            )
        await asyncio.to_thread(self._task.delete_pending_task, task)

    # ── 启动 ──

    async def start_task(self, task_id: str) -> tuple[Any, str]:
        """将 pending 任务加入执行队列。"""
        task = await asyncio.to_thread(self._task.get_task, task_id)
        if task.status is not TaskStatus.PENDING:
            raise TaskAppError(
                "TASK_NOT_PENDING",
                f"只有 pending 任务可以启动，当前状态：{task.status.value}。",
                details={"taskId": task.task_id, "status": task.status.value},
            )
        result = await self._queue.enqueue(task.task_id)
        if result.already_known:
            raise TaskAppError(
                "TASK_ALREADY_SCHEDULED",
                f"任务已处于调度状态：{result.scheduler_status}。",
                details={"taskId": task.task_id, "schedulerStatus": result.scheduler_status},
            )
        return task, result.scheduler_status

    # ── 重试 ──

    async def restart_task(self, task_id: str) -> tuple[Any, str]:
        """重试失败/超时/取消的任务，创建新任务并立即入队。"""
        task = await asyncio.to_thread(self._task.get_task, task_id)
        if task.status not in (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED):
            raise TaskAppError(
                "TASK_NOT_RETRYABLE",
                f"只有失败/超时/取消的任务可以重试，当前状态：{task.status.value}。",
                details={"taskId": task.task_id, "status": task.status.value},
            )
        new_task = await asyncio.to_thread(self._task.restart_task, task)
        try:
            result = await self._queue.enqueue(new_task.task_id)
        except Exception:
            # 入队失败需要回滚新建的任务，同样走线程池。
            await asyncio.to_thread(self._task.delete_pending_task, new_task)
            raise
        if result.already_known:
            await asyncio.to_thread(self._task.delete_pending_task, new_task)
            raise TaskAppError(
                "TASK_ALREADY_SCHEDULED",
                f"新创建的任务意外处于已调度状态：{result.scheduler_status}。",
                details={"taskId": new_task.task_id, "schedulerStatus": result.scheduler_status},
            )
        return new_task, result.scheduler_status

    # ── 取消失败/已终态校验 ──

    async def _check_not_finished(self, task_id: str) -> tuple[Any, str | None]:
        """获取任务并校验未处于终态。返回 (task, scheduler_status)。"""
        task = await asyncio.to_thread(self._task.get_task, task_id)
        scheduler_status = await self._queue.scheduler_status(task_id)
        if task.status in (
            TaskStatus.CANCELLED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
        ):
            raise TaskAppError(
                "TASK_ALREADY_FINISHED",
                f"任务已处于终态，不能操作：{task.status.value}。",
                http_status=400,
                details={"taskId": task_id, "status": task.status.value},
            )
        return task, scheduler_status

    async def cancel_task(self, task_id: str) -> tuple[Any, str | None]:
        """取消任务。pending/queued 从队列移除；running 通过信号量中断。"""
        task, scheduler_status = await self._check_not_finished(task_id)
        if scheduler_status == "queued":
            await self._queue.cancel(task_id)
        task = await asyncio.to_thread(self._task.cancel_task, task)
        return task, await self._queue.scheduler_status(task.task_id)

    async def stop_task(self, task_id: str) -> tuple[Any, str | None]:
        """强制终止任务（与 cancel 同行为，语义更强）。"""
        return await self.cancel_task(task_id)

    # ── 暂停/恢复 ──

    async def pause_task(self, task_id: str) -> Any:
        task = await asyncio.to_thread(self._task.get_task, task_id)
        if task.status is not TaskStatus.RUNNING:
            raise TaskAppError(
                "TASK_NOT_RUNNING",
                f"只有运行中的任务可以暂停，当前状态：{task.status.value}。",
                details={"taskId": task.task_id, "status": task.status.value},
            )
        return await asyncio.to_thread(self._task.pause_task, task)

    async def resume_task(self, task_id: str) -> Any:
        task = await asyncio.to_thread(self._task.get_task, task_id)
        if task.status is not TaskStatus.PAUSED:
            raise TaskAppError(
                "TASK_NOT_PAUSED",
                f"只有暂停的任务可以恢复，当前状态：{task.status.value}。",
                details={"taskId": task.task_id, "status": task.status.value},
            )
        return await asyncio.to_thread(self._task.resume_task, task)

    # ── 查询（委托） ──

    def get_task(self, task_id: str) -> Any:
        return self._task.get_task(task_id)

    async def get_task_with_scheduler(self, task_id: str) -> tuple[Any, str | None]:
        task = await asyncio.to_thread(self._task.get_task, task_id)
        sched = await self._queue.scheduler_status(task_id)
        return task, sched

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> list[Any]:
        return self._task.list_task_summaries(
            status=status, project_id=project_id, offset=offset, limit=limit, q=q
        )

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        return self._task.count_tasks(status=status, project_id=project_id, q=q)

    async def snapshot_queue_statuses(self) -> dict[str, str]:
        return await self._queue.snapshot_statuses()

    def get_dashboard_stats(self, recent_limit: int = 8) -> dict[str, Any]:
        """返回仪表盘聚合统计：全量计数与最近任务摘要。

        - tasks_total / running_total：跨页准确（COUNT 走 SQLite 索引）
        - findings_total：当前所有任务的发现项数量
        - recent_tasks：按 created_at 降序的前 ``recent_limit`` 条 task summary
        """
        tasks_total = self._task.count_tasks()
        running_total = self._task.count_tasks(status=TaskStatus.RUNNING)
        findings_total = self._task.count_findings()
        recent = self._task.list_task_summaries(offset=0, limit=recent_limit)
        return {
            "tasks_total": tasks_total,
            "running_total": running_total,
            "findings_total": findings_total,
            "recent_tasks": recent,
        }
