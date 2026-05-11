"""任务收尾与报告生成。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from argus_py.blackbox.evaluator import EvaluationResult
from argus_py.browser.snapshot import redact_href, redact_step_params
from argus_py.core.enums import FindingSeverity, FindingType, TaskStatus
from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.task.models import Task
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)


class Finalizer:
    """处理评估结果写入、任务收尾和报告生成。"""

    def __init__(
        self, service: TaskService, report_generator: ReportGenerator | None = None
    ) -> None:
        self.service = service
        self.report_generator = report_generator or ReportGenerator()

    def append_evaluation(self, task: Task, evaluation: EvaluationResult) -> Task:
        """把评估器发现的问题写回任务。"""
        resolved = task
        for finding in evaluation.findings:
            resolved = self.service.append_finding(
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
            resolved = self.service.append_finding(
                resolved,
                title="黑盒任务失败",
                description=evaluation.reason or "评估器判定目标未成功。",
                severity=FindingSeverity.MEDIUM,
                finding_type=FindingType.FUNCTIONAL,
            )
        return resolved

    def finish_success(self, task: Task, owns_status: bool) -> Task:
        """按调用方式完成任务。从存储重载避免覆盖外部状态变更（cancel/pause）。"""
        latest = self.service.get_latest_task(task)
        if latest.status is not TaskStatus.RUNNING:
            return self.generate_report(latest)
        if owns_status:
            completed = self.service.complete_task(latest, result_summary=task.result_summary)
            return self.generate_report(completed)
        return self.service.save_task(latest)

    def finalize(self, task: Task, owns_status: bool) -> Task:
        """外部终止（cancel/pause）后的收尾，需要时生成报告。"""
        if owns_status and task.status in (TaskStatus.CANCELLED, TaskStatus.PAUSED):
            return self.generate_report(task)
        return task

    def generate_report(self, task: Task) -> Task:
        """生成任务报告并回写 HTML 报告路径。"""
        return generate_report_safely(task, self.report_generator, self.service.save_task)

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
