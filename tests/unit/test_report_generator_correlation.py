"""白盒报告关联数据：ReportGenerator 透传与 regenerate_report_for_analysis。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from argus_py.core.enums import TaskType
from argus_py.report.generator import (
    GeneratedReport,
    ReportGenerator,
    generate_report_safely,
    regenerate_report_for_analysis,
)
from argus_py.report.models import Report
from argus_py.task.models import Task

CORRELATION: dict = {
    "analysisId": "an-1",
    "aggregate": {"runCount": 1, "confirmedTouchedEndpointCount": 2},
    "touchedEndpoints": [{"endpointId": "ep-1", "httpMethod": "GET", "path": "/api/x"}],
    "unmatchedRequests": [],
    "findingRelations": [],
}


def test_report_generator_writes_correlation_section(tmp_path: Path) -> None:
    task = Task(goal="白盒分析", task_type=TaskType.WHITEBOX)
    generated = ReportGenerator(tmp_path / "reports").generate(task, correlation=CORRELATION)

    assert generated.html_path.exists()
    assert generated.json_path.exists()
    html = generated.html_path.read_text(encoding="utf-8")
    assert "黑白盒关联" in html
    assert "确认触达端点" in html

    json_data = json.loads(generated.json_path.read_text(encoding="utf-8"))
    assert json_data["correlation"]["analysisId"] == "an-1"
    assert json_data["correlation"]["aggregate"]["confirmedTouchedEndpointCount"] == 2


def test_report_generator_without_correlation_has_no_section(tmp_path: Path) -> None:
    task = Task(goal="白盒分析", task_type=TaskType.WHITEBOX)
    generated = ReportGenerator(tmp_path / "reports").generate(task)

    html = generated.html_path.read_text(encoding="utf-8")
    # 空态说明仍在，但不应渲染关联指标
    assert "暂无关联数据" in html
    assert "等待关联" in html
    json_data = json.loads(generated.json_path.read_text(encoding="utf-8"))
    assert "correlation" not in json_data


def test_report_renders_degraded_banner(tmp_path: Path) -> None:
    """result_json 含 completeness/qualityIssues → HTML 报告渲染降级横幅。"""
    task = Task(goal="白盒分析", task_type=TaskType.WHITEBOX)
    task.result_json = json.dumps(
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
            "endpoints": [],
            "callGraph": {},
            "executionFlows": [],
            "clusters": [],
            "findings": [],
            "diagnostics": {"classpathAvailable": False},
            "summary": {"scope": "all"},
        },
        ensure_ascii=False,
    )
    generated = ReportGenerator(tmp_path / "reports").generate(task)

    html = generated.html_path.read_text(encoding="utf-8")
    assert "分析部分降级" in html
    assert "CLASSPATH_UNAVAILABLE: Classpath 不可用" in html


def test_report_without_completeness_shows_unknown_state(tmp_path: Path) -> None:
    """旧 result_json（无 completeness key）→ 横幅显示分析状态未知，不误报完整。"""
    task = Task(goal="白盒分析", task_type=TaskType.WHITEBOX)
    task.result_json = json.dumps({"endpoints": [], "callGraph": {}, "findings": []})
    generated = ReportGenerator(tmp_path / "reports").generate(task)

    html = generated.html_path.read_text(encoding="utf-8")
    assert "分析状态未知" in html


class _RecordingGenerator(ReportGenerator):
    """记录每次 generate 调用的 correlation 参数（不实际写盘）。"""

    def __init__(self, received: list[dict]) -> None:
        super().__init__()
        self.calls = 0
        self._received = received

    def generate(
        self,
        task: Task,
        summary: str | None = None,
        correlation: dict | None = None,
    ) -> GeneratedReport:
        self.calls += 1
        self._received.append({"correlation": correlation})
        return GeneratedReport(
            report=Report.from_task(task, summary or "", correlation),
            html_path=Path("x"),
            json_path=Path("x"),
        )


def _record_save(saved: list[Task]) -> Callable[[Task], Task]:
    def save(task: Task) -> Task:
        saved.append(task)
        return task

    return save


def test_generate_report_safely_passes_correlation() -> None:
    received: list[dict] = []
    gen = _RecordingGenerator(received)
    task = Task(goal="分析")
    generate_report_safely(task, gen, _record_save([]), correlation=CORRELATION)

    assert received[0]["correlation"] is CORRELATION


def test_generate_report_safely_no_correlation_defaults_none() -> None:
    received: list[dict] = []
    gen = _RecordingGenerator(received)
    generate_report_safely(Task(goal="分析"), gen, _record_save([]))

    assert received[0]["correlation"] is None


def test_regenerate_report_for_analysis_skips_when_no_correlation() -> None:
    class FakeStorage:
        def get_analysis_run(self, analysis_id: str):
            return type("AR", (), {"task_id": "t-1"})()

        def load(self, task_id: str):
            return Task(task_id="t-1", goal="分析", task_type=TaskType.WHITEBOX)

    def builder(storage, analysis_id):
        return None  # 尚无关联数据

    received: list[dict] = []
    gen = _RecordingGenerator(received)
    saved: list[Task] = []
    regenerate_report_for_analysis(FakeStorage(), builder, gen, _record_save(saved), "an-1")

    assert gen.calls == 0
    assert saved == []


def test_regenerate_report_for_analysis_generates_and_saves() -> None:
    class FakeStorage:
        def get_analysis_run(self, analysis_id: str):
            return type("AR", (), {"task_id": "t-1"})()

        def load(self, task_id: str):
            return Task(task_id="t-1", goal="分析", task_type=TaskType.WHITEBOX)

    def builder(storage, analysis_id):
        return CORRELATION

    received: list[dict] = []
    gen = _RecordingGenerator(received)
    saved: list[Task] = []
    regenerate_report_for_analysis(FakeStorage(), builder, gen, _record_save(saved), "an-1")

    assert received[0]["correlation"] is CORRELATION
    assert len(saved) == 1  # save_task 被调用一次
    assert saved[0].task_id == "t-1"


def test_regenerate_report_for_analysis_skips_non_whitebox() -> None:
    class FakeStorage:
        def get_analysis_run(self, analysis_id: str):
            return type("AR", (), {"task_id": "t-1"})()

        def load(self, task_id: str):
            return Task(task_id="t-1", goal="黑盒", task_type=TaskType.BLACKBOX)

    def builder(storage, analysis_id):
        return CORRELATION

    received: list[dict] = []
    gen = _RecordingGenerator(received)
    saved: list[Task] = []
    regenerate_report_for_analysis(FakeStorage(), builder, gen, _record_save(saved), "an-1")

    assert gen.calls == 0
    assert saved == []
