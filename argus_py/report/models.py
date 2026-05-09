"""报告数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from argus_py.core.ids import generate_report_id
from argus_py.task.models import Finding, Task, TaskLog


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Report:
    """任务报告。"""

    task: Task
    report_id: str = field(default_factory=generate_report_id)
    title: str = "Argus 黑盒测试报告"
    summary: str = ""
    steps: list[TaskLog] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_task(cls, task: Task, summary: str = "") -> "Report":
        """根据任务生成报告对象。"""
        return cls(
            task=task,
            summary=summary or task.result_summary or "",
            steps=task.logs,
            findings=task.findings,
        )
