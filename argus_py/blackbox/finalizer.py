"""任务收尾与报告生成。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from argus_py.blackbox.evaluator import EvaluationResult
from argus_py.core.enums import FindingSeverity, FindingType, TaskStatus
from argus_py.redaction import redact_href, redact_step_params
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.log import TaskLogService
from argus_py.task.models import Task
from argus_py.task.read import TaskReadService

logger = logging.getLogger(__name__)


class Finalizer:
    """处理评估结果写入、任务收尾和报告生成。"""

    def __init__(
        self,
        log_service: TaskLogService,
        lifecycle: TaskLifecycleService,
        reader: TaskReadService,
        report_generator: ReportGenerator | None = None,
    ) -> None:
        self._log = log_service
        self._lifecycle = lifecycle
        self._reader = reader
        self.report_generator = report_generator or ReportGenerator()

    def append_evaluation(self, task: Task, evaluation: EvaluationResult) -> Task:
        """把评估器发现的问题写回任务。"""
        resolved = task
        for finding in evaluation.findings:
            resolved = self._log.append_finding(
                resolved,
                title=finding.title,
                description=finding.description,
                severity=finding.severity,
                finding_type=finding.finding_type,
                url=finding.url,
                location=finding.location,
                screenshot_path=finding.screenshot_path,
            )
        if evaluation.completed and not evaluation.success and not evaluation.findings:
            resolved = self._log.append_finding(
                resolved,
                title="黑盒任务失败",
                description=evaluation.reason or "评估器判定目标未成功。",
                severity=FindingSeverity.MEDIUM,
                finding_type=FindingType.FUNCTIONAL,
            )
        return resolved

    async def finish_success(self, task: Task, owns_status: bool) -> Task:
        """按调用方式完成任务。从存储重载状态避免覆盖外部状态变更（cancel/pause）。"""
        status = self._reader.get_task_status(task.task_id)
        if status is not TaskStatus.RUNNING:
            latest = self._reader.get_task(task.task_id)
            return await self.generate_report(latest)
        if owns_status:
            completed = self._lifecycle.complete_task(task, result_summary=task.result_summary)
            return await self.generate_report(completed)
        latest = self._reader.get_task(task.task_id)
        return self._lifecycle.save_task(latest)

    async def finalize(self, task: Task, owns_status: bool) -> Task:
        """外部终止（cancel/pause）后的收尾，需要时生成报告。"""
        if owns_status and task.status in (TaskStatus.CANCELLED, TaskStatus.PAUSED):
            return await self.generate_report(task)
        return task

    async def generate_report(self, task: Task) -> Task:
        """生成任务报告并回写 HTML 报告路径（在 IO 线程执行，不阻塞事件循环）。"""
        return await asyncio.to_thread(
            generate_report_safely, task, self.report_generator, self._lifecycle.save_task
        )

    def history(self, task: Task) -> list[dict[str, Any]]:
        """生成给 LLM 使用的紧凑历史，对 URL 和文本参数进行脱敏。"""
        return [
            {
                "step_number": log.step_number,
                "action": log.action,
                "result": log.result.value,
                "params": self._redact_params(log.params),
                "url_before": redact_href(log.url_before) if log.url_before else None,
                "url_after": redact_href(log.url_after) if log.url_after else None,
                "screenshot_path": Path(log.screenshot_path).name if log.screenshot_path else None,
                "message": log.message,
                "error": log.error,
                "error_code": log.error_code,
            }
            for log in task.logs
        ]

    def _redact_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """对动作参数中的 URL 和文本进行脱敏，委托给公开工具函数。"""
        return redact_step_params(params)
