"""报告模型、序列化和生成器。"""

from argus_py.report.generator import GeneratedReport, ReportGenerator, generate_report_safely
from argus_py.report.html_report import render_html_report, write_html_report
from argus_py.report.json_report import write_json_report
from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict

__all__ = [
    "GeneratedReport",
    "Report",
    "ReportGenerator",
    "generate_report_safely",
    "render_html_report",
    "report_to_dict",
    "write_html_report",
    "write_json_report",
]
