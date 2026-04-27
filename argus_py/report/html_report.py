"""HTML 报告生成。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from argus_py.core.paths import REPORT_TEMPLATES_DIR
from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict


def render_html_report(
    report: Report,
    template_dir: str | Path = REPORT_TEMPLATES_DIR,
    template_name: str = "blackbox_report.html.j2",
) -> str:
    """渲染 HTML 报告。"""
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(template_name)
    return template.render(report=report_to_dict(report))


def write_html_report(report: Report, path: str | Path) -> Path:
    """写入 HTML 报告。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html_report(report), encoding="utf-8")
    return target
