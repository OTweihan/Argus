"""CLI 输出层（cli/io.py）单元测试 — 白盒降级终端徽标。

本文件在既有 `tests/unit/test_cli_io.py`（覆盖降级/COMPLETE/无 result_json 三例）
基础上扩展：保留全部原始用例，补充 UNAVAILABLE、非法 JSON、黑盒任务静默三个边界用例。
"""

from __future__ import annotations

import json

from argus_py.cli.io import _print_whitebox_degradation
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.task.models import Task


def _task(result_json: str | None) -> Task:
    return Task(
        task_type=TaskType.WHITEBOX,
        goal="分析",
        status=TaskStatus.COMPLETED,
        result_json=result_json,
    )


def test_degraded_prints_warning(capsys) -> None:
    task = _task(
        json.dumps(
            {
                "completeness": "DEGRADED",
                "qualityIssues": [
                    {
                        "code": "CLASSPATH_UNAVAILABLE",
                        "level": "WARNING",
                        "message": "Classpath 不可用，调用解析降级为源码分析",
                        "affectedCount": 5,
                        "totalCount": 5,
                    }
                ],
            }
        )
    )
    _print_whitebox_degradation(task)
    captured = capsys.readouterr()
    assert "白盒分析降级" in captured.err
    assert "Classpath 不可用" in captured.err


def test_complete_prints_nothing(capsys) -> None:
    _print_whitebox_degradation(
        _task(json.dumps({"completeness": "COMPLETE", "qualityIssues": []}))
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_no_result_json_prints_nothing(capsys) -> None:
    _print_whitebox_degradation(_task(None))
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_invalid_json_prints_nothing(capsys) -> None:
    _print_whitebox_degradation(_task("{not-json"))
    captured = capsys.readouterr()
    assert captured.err == ""


def test_unavailable_prints_warning(capsys) -> None:
    _print_whitebox_degradation(
        _task(
            json.dumps(
                {
                    "completeness": "UNAVAILABLE",
                    "qualityIssues": [
                        {
                            "code": "NO_ELIGIBLE_SOURCE_FILES",
                            "level": "ERROR",
                            "message": "无可分析源文件",
                        }
                    ],
                }
            )
        )
    )
    captured = capsys.readouterr()
    assert "白盒结果不可用" in captured.err
    assert "无可分析源文件" in captured.err


def test_blackbox_result_json_prints_nothing(capsys) -> None:
    """黑盒任务的 result_json 无 completeness 键 → 不打印降级徽标。"""
    task = Task(
        task_type=TaskType.BLACKBOX,
        goal="浏览",
        status=TaskStatus.COMPLETED,
        result_json=json.dumps({"steps": 3, "findings": []}),
    )
    _print_whitebox_degradation(task)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
