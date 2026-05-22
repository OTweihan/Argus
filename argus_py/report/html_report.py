"""HTML 报告生成。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from argus_py.core.paths import REPORT_TEMPLATES_DIR
from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict


def render_html_report(
    report: Report,
    template_dir: str | Path = REPORT_TEMPLATES_DIR,
    template_name: str = "blackbox_report.html.j2",
    output_path: str | Path | None = None,
) -> str:
    """渲染 HTML 报告。"""
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["screenshot_src"] = _screenshot_src_filter(output_path)
    env.filters["pretty_json"] = _pretty_json
    env.filters["datetime_short"] = _datetime_short
    template = env.get_template(template_name)
    return template.render(report=report_to_dict(report))


def write_html_report(report: Report, path: str | Path, template_name: str = "blackbox_report.html.j2") -> Path:
    """写入 HTML 报告。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_html_report(report, output_path=target, template_name=template_name),
        encoding="utf-8",
    )
    return target


def _screenshot_src_filter(output_path: str | Path | None):
    """创建截图路径转换过滤器。"""

    def convert(value: str | None) -> str:
        if not value:
            return ""
        path = Path(value)
        if not path.exists() or output_path is None:
            return ""
        relative = os.path.relpath(path, Path(output_path).parent)
        return relative.replace("\\", "/")

    return convert


def _pretty_json(value: Any) -> str:
    """格式化展示 JSON 数据。"""
    return json.dumps(value, ensure_ascii=False, indent=2)


def _datetime_short(value: Any) -> str:
    """将报告时间转换为本地时区，并格式化为 YYYY-MM-DDTHH:MM:SS。"""
    if not value:
        return ""
    if isinstance(value, datetime):
        resolved = value
    else:
        text = str(value)
        try:
            resolved = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text[:19] if len(text) >= 19 else text

    if resolved.tzinfo is not None:
        resolved = resolved.astimezone()
    return resolved.strftime("%Y-%m-%dT%H:%M:%S")
