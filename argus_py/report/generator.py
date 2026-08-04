"""任务报告生成服务。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus_py.core.enums import TaskType
from argus_py.core.paths import REPORTS_DIR
from argus_py.report.html_report import write_html_report
from argus_py.report.json_report import write_json_report
from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict
from argus_py.task.models import Task

SaveTask = Callable[[Task], Task]

# correlation_builder(storage, analysis_id) -> dict | None
CorrelationBuilder = Callable[[Any, str], dict | None]


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

    def generate(
        self,
        task: Task,
        summary: str | None = None,
        correlation: dict | None = None,
    ) -> GeneratedReport:
        """生成任务报告文件。

        correlation 为白盒任务的关联数据（跨运行聚合），None 表示尚无关联运行。
        """
        target_dir = self.report_dir(task)
        json_path = target_dir / "report.json"
        html_path = target_dir / "index.html"
        original_report_path = task.report_path
        task.report_path = str(html_path)
        try:
            report = Report.from_task(
                task,
                summary=summary or "",
                correlation=correlation,
            )
            report_dict = report_to_dict(report)
            write_json_report(report_dict, json_path)
            template_name = (
                "whitebox_report.html.j2"
                if task.task_type == TaskType.WHITEBOX
                else "blackbox_report.html.j2"
            )
            write_html_report(report_dict, html_path, template_name=template_name)
            return GeneratedReport(report=report, html_path=html_path, json_path=json_path)
        except Exception:
            task.report_path = original_report_path
            raise


logger = logging.getLogger(__name__)


def generate_report_safely(
    task: Task,
    report_generator: ReportGenerator,
    save_task: SaveTask,
    correlation: dict | None = None,
) -> Task:
    """尽力生成报告，不让报告错误覆盖原始任务结果。"""
    try:
        generated = report_generator.generate(task, correlation=correlation)
        task.report_path = str(generated.html_path)
    except Exception as exc:
        message = f"报告生成失败：{exc}"
        logger.exception("任务 %s 报告生成失败: %s", task.task_id, exc)
        if task.error_message:
            task.error_message = f"{task.error_message}；{message}"
        else:
            task.error_message = message
    return save_task(task)


def regenerate_report_for_analysis(
    storage: Any,
    correlation_builder: CorrelationBuilder,
    report_generator: ReportGenerator,
    save_task: SaveTask,
    analysis_id: str,
) -> None:
    """关联 Attempt 完成后重新生成该白盒任务的报告（同步；调用方负责线程与锁）。

    correlation_builder(storage, analysis_id) 返回 None 时跳过（尚无关联数据），
    保持白盒任务最初生成的报告不变。
    """
    analysis_run = storage.get_analysis_run(analysis_id)
    if analysis_run is None:
        return
    task = storage.load(analysis_run.task_id)
    if task is None or task.task_type != TaskType.WHITEBOX:
        return
    correlation = correlation_builder(storage, analysis_id)
    if not correlation:
        return
    generate_report_safely(task, report_generator, save_task, correlation=correlation)
