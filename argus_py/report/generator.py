"""任务报告生成服务。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from argus_py.core.paths import REPORTS_DIR
from argus_py.report.html_report import write_html_report
from argus_py.report.json_report import write_json_report
from argus_py.report.models import Report
from argus_py.task.models import Task

SaveTask = Callable[[Task], Task]


@dataclass(frozen=True)
class GeneratedReport:
    """报告生成结果。"""

    report: Report
    html_path: Path
    json_path: Path


class ReportGenerator:
    """根据任务生成 HTML 和 JSON 报告。"""

    def __init__(self, base_dir: str | Path = REPORTS_DIR) -> None:
        self.base_dir = Path(base_dir)

    def report_dir(self, task: Task) -> Path:
        """返回任务报告目录。"""
        return self.base_dir / task.task_id

    def generate(self, task: Task, summary: str | None = None) -> GeneratedReport:
        """生成任务报告文件。"""
        target_dir = self.report_dir(task)
        json_path = target_dir / "report.json"
        html_path = target_dir / "index.html"
        original_report_path = task.report_path
        task.report_path = str(html_path)
        try:
            report = Report.from_task(task, summary=summary or "")
            write_json_report(report, json_path)
            write_html_report(report, html_path)
            return GeneratedReport(report=report, html_path=html_path, json_path=json_path)
        except Exception:
            task.report_path = original_report_path
            raise


logger = logging.getLogger(__name__)


def generate_report_safely(
    task: Task,
    report_generator: ReportGenerator,
    save_task: SaveTask,
) -> Task:
    """尽力生成报告，不让报告错误覆盖原始任务结果。"""
    try:
        generated = report_generator.generate(task)
        task.report_path = str(generated.html_path)
    except Exception as exc:
        message = f"报告生成失败：{exc}"
        logger.warning("任务 %s 报告生成失败: %s", task.task_id, exc)
        if task.error_message:
            task.error_message = f"{task.error_message}；{message}"
        else:
            task.error_message = message
    return save_task(task)
