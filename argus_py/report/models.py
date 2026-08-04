"""报告数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from argus_py.core.constants import utc_now
from argus_py.core.enums import TaskType
from argus_py.core.ids import generate_report_id
from argus_py.task.models import Finding, Task, TaskLog


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
    # 白盒任务的关联数据（由 build_correlation_report_data 提供）。
    # None 表示尚无关联运行，序列化时移除该键，保持黑盒/未关联报告输出不变。
    correlation: dict | None = None

    @classmethod
    def from_task(
        cls,
        task: Task,
        summary: str = "",
        correlation: dict | None = None,
    ) -> "Report":
        """根据任务生成报告对象。"""
        if task.task_type == TaskType.WHITEBOX:
            title = "Argus 白盒分析报告"
        else:
            title = "Argus 黑盒测试报告"
        return cls(
            task=task,
            title=title,
            summary=summary or task.result_summary or "",
            steps=task.logs,
            findings=task.findings,
            correlation=correlation,
        )
