"""任务应用服务层：编排 TaskService + TaskQueue + ProjectService + ModelConfigService。

HTTP 路由只做参数/响应转换，所有业务编排逻辑集中在此。
CLI 也可复用此类避免重复编排逻辑。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from argus_py.browser.url_validator import validate_url
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.exceptions import TaskError
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
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.task.strategy import resolve_execution_limits
from argus_py.utils.casing import camel_keys


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
            max_steps = max_steps or project.default_max_steps
            timeout_seconds = timeout_seconds or project.default_timeout_seconds
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
        result = await self._queue.enqueue(task.task_id)
        if result.already_known:
            raise TaskAppError(
                "TASK_ALREADY_SCHEDULED",
                f"任务已处于调度状态：{result.scheduler_status}。",
                details={"task_id": task.task_id, "scheduler_status": result.scheduler_status},
            )
        return task, result.scheduler_status

    # ── 重试 ──

    async def restart_task(self, task_id: str) -> tuple[Any, str]:
        """重试失败/超时/取消的任务，创建新任务并立即入队。"""
        task = await run_in_thread(self._read.get_task, task_id)
        if not can_retry(task.status):
            raise TaskAppError(
                "TASK_NOT_RETRYABLE",
                f"只有失败/超时/取消的任务可以重试，当前状态：{task.status.value}。",
                details={"task_id": task.task_id, "status": task.status.value},
            )
        new_task = await run_in_thread(self._lifecycle.restart_task, task)
        try:
            result = await self._queue.enqueue(new_task.task_id)
        except (Exception, asyncio.CancelledError):
            # enqueue 内部 await self._queue.put() 不会抛 QueueFull，但可能因
            # 协程取消或其它异常终止。无论哪种异常，new_task 已写入 DB，必须回滚。
            await run_in_thread(self._lifecycle.delete_pending_task, new_task)
            raise
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

    def get_task(self, task_id: str) -> Any:
        return self._read.get_task(task_id)

    async def get_task_with_scheduler(self, task_id: str) -> tuple[Any, str | None]:
        task = await run_in_thread(self._read.get_task, task_id)
        sched = await self._queue.scheduler_status(task_id)
        return task, sched

    def list_task_summaries(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Any], int]:
        return self._read.list_task_summaries(
            status=status, project_id=project_id, offset=offset, limit=limit, q=q
        )

    def count_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        q: str | None = None,
    ) -> int:
        return self._read.count_tasks(status=status, project_id=project_id, q=q)

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
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_analysis_runs(task_id, offset=offset, limit=limit)
        return [], 0

    def get_latest_analysis_run(self, task_id: str) -> Any:
        """获取任务的最近一次分析执行。"""
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_latest_analysis_run(task_id)
        return None

    def get_analysis_run(self, analysis_id: str) -> Any:
        """按 ID 获取分析执行详情。"""
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_analysis_run(analysis_id)
        return None

    def list_analysis_endpoints(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_analysis_endpoints(analysis_id, cursor=cursor, limit=limit)
        return [], None, 0, False

    def list_analysis_call_nodes(
        self,
        analysis_id: str,
        *,
        class_name: str | None = None,
        method_name: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_analysis_call_nodes(
                analysis_id,
                class_name=class_name,
                method_name=method_name,
                cursor=cursor,
                limit=limit,
            )
        return [], None, 0, False

    def list_analysis_call_edges(
        self,
        analysis_id: str,
        *,
        entry_node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_analysis_call_edges(
                analysis_id,
                entry_node_id=entry_node_id,
                cursor=cursor,
                limit=limit,
            )
        return [], None, 0, False

    def list_analysis_execution_flows(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None, int | None, bool]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_analysis_execution_flows(analysis_id, cursor=cursor, limit=limit)
        return [], None, 0, False

    def list_analysis_clusters(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[Any], str | None, int | None, bool]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_analysis_clusters(analysis_id, cursor=cursor, limit=limit)
        return [], None, 0, False

    def get_analysis_diagnostics(self, analysis_id: str) -> dict[str, Any] | None:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_analysis_diagnostics(analysis_id)
        return None

    def get_analysis_counts(self, analysis_id: str) -> dict[str, int]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_analysis_counts(analysis_id)
        return {}

    def get_analysis_finding_severity_counts(self, analysis_id: str) -> dict[str, int]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_analysis_finding_severity_counts(analysis_id)
        return {}

    def get_analysis_flow_steps(self, flow_id: str) -> list[dict[str, Any]]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_analysis_flow_steps(flow_id)
        return []

    def get_analysis_findings(
        self, analysis_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[Any], str | None, int | None, bool]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_analysis_findings(analysis_id, cursor=cursor, limit=limit)
        return [], None, 0, False

    # ── 关联（CorrelationRun / Evidence）──────────────────────

    def list_correlation_runs_by_task(self, task_id: str) -> list[dict[str, Any]]:
        """通过 taskId 查找所有关联运行。"""
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            bb_runs = storage._correlation.list_blackbox_runs_by_task(task_id)
            result: list[dict[str, Any]] = []
            for bb in bb_runs:
                cr = storage.get_correlation_run_by_blackbox(bb.blackbox_run_id)
                if cr is not None:
                    result.append(_correlation_run_to_dict(cr))
            return result
        return []

    def get_correlation_run(self, correlation_run_id: str) -> dict[str, Any] | None:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            cr = storage.get_correlation_run(correlation_run_id)
            if cr is None:
                return None
            return _correlation_run_to_dict(cr)
        return None

    def list_correlation_attempts(self, correlation_run_id: str) -> list[dict[str, Any]]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            attempts = storage._correlation.list_attempts_by_run(correlation_run_id)
            return [_attempt_to_dict(a) for a in attempts]
        return []

    def get_correlation_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            attempt = storage._correlation.get_attempt(attempt_id)
            if attempt is None:
                return None
            return _attempt_to_dict(attempt)
        return None

    def get_correlation_summary(self, correlation_run_id: str) -> dict[str, Any]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            summary = storage.get_correlation_summary(correlation_run_id)
            return _summary_to_dict(summary)
        return {}

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
        if isinstance(storage, TaskSQLiteStorage):
            cr = storage.get_correlation_run(correlation_run_id)
            if cr is None or cr.active_attempt_id is None:
                return [], 0
            items, total = storage._correlation.list_evidence_by_attempt(
                cr.active_attempt_id,
                resolution_status=resolution_status,
                match_strategy=match_strategy,
                offset=offset,
                limit=limit,
            )

            if not items:
                return [], total

            # ── 组装 matchedEndpointInfo / candidates / executionFlows ──
            matched_ids = [
                it["matched_endpoint_id"] for it in items if it.get("matched_endpoint_id")
            ]
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
        return [], 0

    def list_unmatched_requests(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            items, total = storage.list_unmatched_requests(
                correlation_run_id,
                offset=offset,
                limit=limit,
            )
            return [_http_request_to_dict(r) for r in items], total
        return [], 0

    def list_finding_evidence(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
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
        return [], 0

    def get_capture_quality(self, blackbox_run_id: str) -> dict[str, Any] | None:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.get_capture_quality(blackbox_run_id)
        return None

    # ── 关联操作 ──

    def bind_analysis(
        self,
        correlation_run_id: str,
        analysis_id: str,
        expected_projection_version: int | None = None,
        source_mismatch_override: bool = False,
        source_mismatch_override_reason: str | None = None,
    ) -> None:
        """手动绑定白盒分析到关联运行，完成校验后推进状态。

        校验：分析必须存在且为 SUCCEEDED；分析任务与关联运行必须属于同一项目。
        绑定后会检查黑盒是否已完成，已完成则直接进入 READY。
        """
        storage = self._read.storage
        if not isinstance(storage, TaskSQLiteStorage):
            raise ValueError("当前存储不支持关联操作。")

        # 1. 校验分析存在且成功
        analysis_run = storage.get_analysis_run(analysis_id)
        if analysis_run is None:
            raise ValueError(f"分析执行不存在：{analysis_id}")
        if getattr(analysis_run, "run_status", "") != "SUCCEEDED":
            raise ValueError(
                f"只有成功的分析可以绑定，当前状态：{getattr(analysis_run, 'run_status', '')}"
            )

        # 2. 校验关联运行存在且尚未绑定分析
        cr = storage.get_correlation_run(correlation_run_id)
        if cr is None:
            raise ValueError(f"关联运行不存在：{correlation_run_id}")
        if cr.analysis_id is not None:
            raise ValueError(f"关联运行已绑定分析：{cr.analysis_id}")

        # 3. 校验项目一致
        analysis_task_header = storage.load_task_header(analysis_run.task_id)
        if analysis_task_header is None:
            raise ValueError(f"分析任务不存在：{analysis_run.task_id}")
        analysis_project = analysis_task_header.get("project_id", "")
        if analysis_project and cr.project_id and analysis_project != cr.project_id:
            raise ValueError(
                f"项目不一致：关联运行项目={cr.project_id}，分析任务项目={analysis_project}"
            )

        # 4. 确定 alignment — 优先从分析读取快照
        analysis_snapshot = getattr(analysis_run, "resolved_commit_sha", None) or ""
        cr_desired = cr.desired_source_snapshot_id or ""

        # 快照不一致时必须显式 override，不允许静默绑定
        if analysis_snapshot and cr_desired and analysis_snapshot != cr_desired:
            if not source_mismatch_override:
                raise ValueError(
                    f"分析快照 ({analysis_snapshot[:8]}) 与关联运行期望快照 "
                    f"({cr_desired[:8]}) 不一致，请确认覆盖绑定。"
                )
            alignment = "USER_DECLARED"
        elif source_mismatch_override:
            alignment = "USER_DECLARED"
        elif analysis_snapshot and cr_desired and analysis_snapshot == cr_desired:
            alignment = "VERIFIED"
        else:
            alignment = "UNVERIFIED"

        # 持久化 override 审计字段
        override_at = datetime.now(timezone.utc).isoformat() if source_mismatch_override else None

        storage.bind_correlation_analysis(
            correlation_run_id,
            analysis_id,
            snapshot_id=analysis_snapshot,
            projection_version=expected_projection_version or 1,
            alignment=alignment,
            source_mismatch_overridden=source_mismatch_override,
            source_mismatch_override_by=None,  # TODO: 从 auth 上下文注入操作者
            source_mismatch_override_at=override_at,
            source_mismatch_override_reason=source_mismatch_override_reason,
        )

        # 5. 根据黑盒完成状态推进
        from argus_py.correlation.enums import BlackboxRunStatus

        bb_run = storage.get_blackbox_run(cr.blackbox_run_id)
        bb_done = bb_run is not None and bb_run.status in (
            BlackboxRunStatus.SUCCESS,
            BlackboxRunStatus.FAILED,
            BlackboxRunStatus.CANCELLED,
            BlackboxRunStatus.TIMED_OUT,
        )
        if bb_done:
            storage.set_correlation_status(correlation_run_id, "READY")
            # 立即认领并执行关联匹配，避免永久停在 READY
            updated_cr = storage.get_correlation_run(correlation_run_id)
            if updated_cr is not None and updated_cr.analysis_id is not None:
                from argus_py.core.ids import generate_id

                worker_id = generate_id("bind")
                attempt = storage.claim_and_create_attempt(correlation_run_id, worker_id)
                if attempt is not None:
                    try:
                        _execute_matching_sync(storage, updated_cr, attempt)
                    except Exception:
                        from argus_py.correlation.enums import AttemptStatus, EvidenceCompleteness

                        storage.complete_and_activate_attempt(
                            attempt.correlation_attempt_id,
                            AttemptStatus.FAILED.value,
                            EvidenceCompleteness.PARTIAL.value,
                        )
        else:
            storage.set_correlation_status(correlation_run_id, "WAITING_BLACKBOX")

    def list_uncovered_endpoints(
        self,
        correlation_run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        storage = self._read.storage
        if isinstance(storage, TaskSQLiteStorage):
            return storage.list_uncovered_endpoints(
                correlation_run_id,
                offset=offset,
                limit=limit,
            )
        return [], 0

    def retry_correlation(self, correlation_run_id: str) -> str:
        """将 FAILED/PARTIAL 的关联运行重置为 READY，创建新 attempt 并同步执行匹配。"""
        from argus_py.correlation.enums import CorrelationRunStatus

        storage = self._read.storage
        if not isinstance(storage, TaskSQLiteStorage):
            raise ValueError("当前存储不支持关联重试。")
        cr = storage.get_correlation_run(correlation_run_id)
        if cr is None:
            raise ValueError(f"关联运行不存在：{correlation_run_id}")
        if cr.status not in (CorrelationRunStatus.FAILED, CorrelationRunStatus.PARTIAL):
            raise ValueError(f"只有失败或部分完成的关联可以重试，当前状态：{cr.status.value}")
        if cr.analysis_id is None:
            raise ValueError("无法重试：尚未绑定白盒分析。")

        from argus_py.core.ids import generate_id

        worker_id = generate_id("retry")
        storage.set_correlation_status(correlation_run_id, "READY")
        attempt = storage.claim_and_create_attempt(correlation_run_id, worker_id)
        if attempt is None:
            raise ValueError("认领关联运行失败，可能已被其他 Worker 执行。")

        try:
            _execute_matching_sync(storage, cr, attempt)
        except Exception:
            from argus_py.correlation.enums import AttemptStatus, EvidenceCompleteness

            storage.complete_and_activate_attempt(
                attempt.correlation_attempt_id,
                AttemptStatus.FAILED.value,
                EvidenceCompleteness.PARTIAL.value,
            )
            raise

        return attempt.correlation_attempt_id

    def recalculate_correlation(self, correlation_run_id: str) -> dict[str, Any] | None:
        """创建新 CorrelationRun（supersedes 指向前一个）并同步执行匹配。"""
        import uuid as _uuid_mod
        from datetime import datetime as dt_mod
        from datetime import timezone

        from argus_py.correlation.enums import (
            AttemptStatus,
            CorrelationRunStatus,
            EvidenceCompleteness,
        )
        from argus_py.correlation.models import CorrelationRun
        from argus_py.correlation.path_utils import compute_config_digest

        storage = self._read.storage
        if not isinstance(storage, TaskSQLiteStorage):
            return None
        existing = storage.get_correlation_run(correlation_run_id)
        if existing is None:
            return None
        if existing.analysis_id is None:
            raise ValueError("无法重算：尚未绑定白盒分析。")

        digest = compute_config_digest(
            existing.matcher_version,
            existing.normalization_version,
        )
        new_cr = CorrelationRun(
            correlation_run_id=f"cr:{_uuid_mod.uuid4().hex[:12]}",
            project_id=existing.project_id,
            blackbox_run_id=existing.blackbox_run_id,
            desired_source_snapshot_id=existing.desired_source_snapshot_id,
            desired_analysis_config_digest=existing.desired_analysis_config_digest,
            required_analyzer_version=existing.required_analyzer_version,
            allow_partial_analysis=existing.allow_partial_analysis,
            analysis_id=existing.analysis_id,
            bound_source_snapshot_id=existing.bound_source_snapshot_id,
            analysis_projection_version=existing.analysis_projection_version,
            correlation_config_digest=digest,
            matcher_version=existing.matcher_version,
            normalization_version=existing.normalization_version,
            supersedes_correlation_run_id=existing.correlation_run_id,
            source_alignment_status=existing.source_alignment_status,
            status=CorrelationRunStatus.READY,
            created_at=dt_mod.now(timezone.utc).isoformat(),
        )
        storage.create_correlation_run(new_cr)

        # CAS 认领 + 同步执行匹配
        from argus_py.core.ids import generate_id

        worker_id = generate_id("recalc")
        attempt = storage.claim_and_create_attempt(new_cr.correlation_run_id, worker_id)
        if attempt is None:
            raise ValueError("认领关联运行失败，可能已被其他 Worker 执行。")

        try:
            _execute_matching_sync(storage, new_cr, attempt)
        except Exception:
            storage.complete_and_activate_attempt(
                attempt.correlation_attempt_id,
                AttemptStatus.FAILED.value,
                EvidenceCompleteness.PARTIAL.value,
            )
            raise

        return _correlation_run_to_dict(new_cr)


# ── 同步匹配执行器（run_in_thread 可调用）──────────────────────────


def _execute_matching_sync(storage: Any, cr: Any, attempt: Any) -> None:
    """关联匹配的同步实现 — 纯 CPU + 同步 SQLite 操作。

    根据采集质量和匹配结果决定 completeness（COMPLETE/PARTIAL），
    并写入对应的 reasons 和 diagnostics。
    """
    from argus_py.correlation._execution import (
        assess_capture_quality,
        build_quality_reasons,
        generate_finding_evidence,
        generate_flows,
        resolve_completeness,
    )
    from argus_py.correlation.enums import (
        AttemptDiagnosticCode,
        AttemptStatus,
        EvidenceCompleteness,
    )
    from argus_py.correlation.matcher import EndpointMatcher
    from argus_py.correlation.models import (
        CorrelationAttemptDiagnostic,
    )

    if cr.analysis_id is None:
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            AttemptStatus.FAILED.value,
            EvidenceCompleteness.PARTIAL.value,
        )
        return

    # ── 读取采集质量 ──
    cq = storage.get_capture_quality(cr.blackbox_run_id)
    capture_truncated, has_persistence_failure = assess_capture_quality(cq)
    reasons, diagnostics = build_quality_reasons(
        attempt.correlation_attempt_id,
        cq,
        capture_truncated,
        has_persistence_failure,
    )

    endpoints_result = storage.list_analysis_endpoints(cr.analysis_id, limit=10_000)
    endpoints_list = endpoints_result[0]
    eligible_requests = storage.list_eligible_requests(cr.blackbox_run_id)

    if not eligible_requests:
        diagnostics.append(
            CorrelationAttemptDiagnostic(
                correlation_attempt_id=attempt.correlation_attempt_id,
                diagnostic_code=AttemptDiagnosticCode.NO_ELIGIBLE_REQUESTS,
                detail=f"blackbox_run_id={cr.blackbox_run_id} 无 CONFIRMED_ELIGIBLE 请求",
            )
        )
        completeness = resolve_completeness(
            bool(reasons),
            capture_truncated,
            has_persistence_failure,
        )
        if reasons:
            storage.insert_attempt_reasons_batch(reasons)
        if diagnostics:
            storage.insert_attempt_diagnostics_batch(diagnostics)
        storage.complete_and_activate_attempt(
            attempt.correlation_attempt_id,
            (
                AttemptStatus.PARTIAL
                if completeness == EvidenceCompleteness.PARTIAL
                else AttemptStatus.SUCCEEDED
            ).value,
            completeness.value,
        )
        return

    matcher = EndpointMatcher(matcher_version="v1", normalization_version="v1")
    result = matcher.match_batch(eligible_requests, endpoints_list)

    if result.diagnostics:
        diagnostics.extend(
            CorrelationAttemptDiagnostic(
                correlation_attempt_id=attempt.correlation_attempt_id,
                diagnostic_code=d,
                detail=None,
            )
            for d in result.diagnostics
        )

    for ev in result.evidence_list:
        ev.correlation_run_id = cr.correlation_run_id
        ev.correlation_attempt_id = attempt.correlation_attempt_id

    storage.insert_endpoint_evidence_batch(result.evidence_list)
    if result.candidates:
        storage.insert_candidates_batch(result.candidates)

    # ── 生成调用流关联 ──
    flows = generate_flows(storage, cr.analysis_id, result.evidence_list, endpoints_list)
    if flows:
        storage.insert_flows_batch(flows)

    # ── 生成 Finding 证据关联 ──
    finding_evidence_list, finding_links = generate_finding_evidence(
        storage,
        cr.analysis_id,
        attempt.correlation_attempt_id,
        result.evidence_list,
        endpoints_list,
    )
    if finding_evidence_list:
        storage.insert_finding_evidence_batch(finding_evidence_list)
    if finding_links:
        storage.insert_finding_links_batch(finding_links)

    completeness = resolve_completeness(
        bool(reasons),
        capture_truncated,
        has_persistence_failure,
    )
    if reasons:
        storage.insert_attempt_reasons_batch(reasons)
    if diagnostics:
        storage.insert_attempt_diagnostics_batch(diagnostics)

    storage.complete_and_activate_attempt(
        attempt.correlation_attempt_id,
        (
            AttemptStatus.PARTIAL
            if completeness == EvidenceCompleteness.PARTIAL
            else AttemptStatus.SUCCEEDED
        ).value,
        completeness.value,
    )


# ── 关联字典转换辅助（模块级）──────────────────────────────────────


def _correlation_run_to_dict(cr: Any) -> dict[str, Any]:
    """将 CorrelationRun 实体转为 dict（camelCase keys for API）。"""
    return {
        "correlationRunId": cr.correlation_run_id,
        "projectId": cr.project_id,
        "blackboxRunId": cr.blackbox_run_id,
        "desiredSourceSnapshotId": cr.desired_source_snapshot_id,
        "desiredAnalysisConfigDigest": cr.desired_analysis_config_digest,
        "requiredAnalyzerVersion": cr.required_analyzer_version,
        "allowPartialAnalysis": cr.allow_partial_analysis,
        "analysisId": cr.analysis_id,
        "boundSourceSnapshotId": cr.bound_source_snapshot_id,
        "analysisProjectionVersion": cr.analysis_projection_version,
        "correlationConfigDigest": cr.correlation_config_digest,
        "matcherVersion": cr.matcher_version,
        "normalizationVersion": cr.normalization_version,
        "supersedesCorrelationRunId": cr.supersedes_correlation_run_id,
        "sourceAlignmentStatus": (
            cr.source_alignment_status.value
            if hasattr(cr.source_alignment_status, "value")
            else str(cr.source_alignment_status)
        ),
        "status": cr.status.value if hasattr(cr.status, "value") else str(cr.status),
        "activeAttemptId": cr.active_attempt_id,
        "sourceMismatchOverridden": cr.source_mismatch_overridden,
        "sourceMismatchOverrideBy": cr.source_mismatch_override_by,
        "sourceMismatchOverrideAt": cr.source_mismatch_override_at,
        "sourceMismatchOverrideReason": cr.source_mismatch_override_reason,
        "startedAt": cr.started_at,
        "completedAt": cr.completed_at,
        "errorCode": cr.error_code,
        "errorMessage": cr.error_message,
        "createdAt": cr.created_at,
    }


def _attempt_to_dict(a: Any) -> dict[str, Any]:
    """将 CorrelationAttempt 实体转为 dict。"""
    return {
        "correlationAttemptId": a.correlation_attempt_id,
        "correlationRunId": a.correlation_run_id,
        "attemptNumber": a.attempt_number,
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "evidenceCompleteness": (
            a.evidence_completeness.value
            if hasattr(a.evidence_completeness, "value")
            else str(a.evidence_completeness)
        ),
        "leaseOwner": a.lease_owner,
        "startedAt": a.started_at,
        "completedAt": a.completed_at,
        "errorCode": a.error_code,
        "errorMessage": a.error_message,
        "createdAt": a.created_at,
    }


def _summary_to_dict(s: Any) -> dict[str, Any]:
    """将 CorrelationSummary 转为 dict。"""
    if s is None:
        return {}
    return {
        "correlationRunId": s.correlation_run_id,
        "status": s.status,
        "sourceAlignmentStatus": s.source_alignment_status,
        "capturedRequestCount": s.captured_request_count,
        "correlatableRequestCount": s.correlatable_request_count,
        "confirmedMatchedRequestCount": s.confirmed_matched_request_count,
        "ambiguousRequestCount": s.ambiguous_request_count,
        "methodMismatchCandidateCount": s.method_mismatch_candidate_count,
        "unmatchedRequestCount": s.unmatched_request_count,
        "totalEndpointCount": s.total_endpoint_count,
        "confirmedTouchedEndpointCount": s.confirmed_touched_endpoint_count,
        "candidateTouchedEndpointCount": s.candidate_touched_endpoint_count,
        "uncoveredEndpointCount": s.uncovered_endpoint_count,
        "attemptedEvidenceCount": s.attempted_evidence_count,
        "totalFindingCount": s.total_finding_count,
        "confirmedRelatedFindingCount": s.confirmed_related_finding_count,
        "candidateRelatedFindingCount": s.candidate_related_finding_count,
        "unrelatedFindingCount": s.unrelated_finding_count,
        "crossOriginFilteredCount": s.cross_origin_filtered_count,
        "resourceFilteredCount": s.resource_filtered_count,
        "droppedRequestCount": s.dropped_request_count,
        "failedCaptureCount": s.failed_capture_count,
        "evidenceCompleteness": s.evidence_completeness,
        "matcherVersion": s.matcher_version,
        "normalizationVersion": s.normalization_version,
    }


def _http_request_to_dict(req: Any) -> dict[str, Any]:
    """将 HttpRequestEvidence 实体转为 dict。"""
    return {
        "requestEvidenceId": req.request_evidence_id,
        "blackboxRunId": req.blackbox_run_id,
        "taskId": req.task_id,
        "stepExecutionId": req.step_execution_id,
        "stepAttempt": req.step_attempt,
        "requestSequence": req.request_sequence,
        "httpMethod": req.http_method,
        "displayPath": req.display_path,
        "origin": req.origin,
        "resourceType": req.resource_type,
        "endpointMatchEligibility": (
            req.endpoint_match_eligibility.value
            if hasattr(req.endpoint_match_eligibility, "value")
            else str(req.endpoint_match_eligibility)
        ),
        "responseStatus": req.response_status,
        "outcome": req.outcome.value if hasattr(req.outcome, "value") else str(req.outcome),
        "requestOwner": (
            req.request_owner.value
            if hasattr(req.request_owner, "value")
            else str(req.request_owner)
        ),
        "responseFromServiceWorker": req.response_from_service_worker,
        "pageSequence": req.page_sequence,
        "capturedAt": req.captured_at,
        "finishedAt": req.finished_at,
    }
