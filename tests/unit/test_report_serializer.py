from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict
from argus_py.task.models import Task, TaskLog


def test_report_to_dict():
    report = Report.from_task(Task(goal="打开页面"))
    data = report_to_dict(report)

    assert data["task"]["goal"] == "打开页面"
    assert data["reportId"].startswith("report-")


def test_report_to_dict_no_correlation_key_absent():
    """无关联数据时 correlation 键必须移除，保持黑盒/未关联白盒报告输出不变。"""
    report = Report.from_task(Task(goal="打开页面"))
    data = report_to_dict(report)
    assert "correlation" not in data


def test_report_to_dict_correlation_section_preserved():
    """camelCase 嵌套关联数据经序列化后原样保留（camel_keys_inplace 不改名）。"""
    correlation = {
        "analysisId": "an-1",
        "aggregate": {"runCount": 2, "confirmedTouchedEndpointCount": 3},
        "touchedEndpoints": [
            {"endpointId": "ep-1", "httpMethod": "GET", "confirmedRequestCount": 5},
        ],
        "unmatchedRequests": [
            {
                "httpMethod": "GET",
                "displayPath": "/api/users/0f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6a7b8c9d",
            },
        ],
        "findingRelations": [
            {"findingId": "f-1", "title": "空 catch", "severity": "high"},
        ],
    }
    report = Report.from_task(Task(goal="分析"), correlation=correlation)
    data = report_to_dict(report)

    assert data["correlation"]["analysisId"] == "an-1"
    assert data["correlation"]["aggregate"]["runCount"] == 2
    assert data["correlation"]["touchedEndpoints"][0]["confirmedRequestCount"] == 5
    # snake_case key 不会被意外引入
    assert "confirmed_request_count" not in data["correlation"]["touchedEndpoints"][0]


def test_report_correlation_redacts_unmatched_display_path_and_finding():
    """关联数据脱敏：未匹配请求路径 token→{token}，finding 文本含 [REDACTED]。"""
    correlation = {
        "analysisId": "an-1",
        "unmatchedRequests": [
            {
                "httpMethod": "GET",
                "displayPath": "/api/users/0f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6a7b8c9d",
            },
        ],
        "findingRelations": [
            {
                "findingId": "f-1",
                "title": "token=secret123",
                "location": "App.java:1?api_key=abc123",
                "severity": "high",
            },
        ],
    }
    data = report_to_dict(Report.from_task(Task(goal="分析"), correlation=correlation))

    corr = data["correlation"]
    assert corr["unmatchedRequests"][0]["displayPath"] == "/api/users/{token}"
    assert "[REDACTED]" in corr["findingRelations"][0]["title"]
    assert "[REDACTED]" in corr["findingRelations"][0]["location"]


def test_report_to_dict_hides_internal_success_steps():
    task = Task(goal="测试新增用户")
    task.logs.extend(
        [
            TaskLog(step_number=1, action="goto", message="打开页面"),
            TaskLog(step_number=2, action="wait", message="等待弹窗加载"),
            TaskLog(step_number=3, action="screenshot", message="截图已保存。"),
            TaskLog(step_number=4, action="click", message="提交空表单"),
        ]
    )

    data = report_to_dict(Report.from_task(task))

    assert [step["action"] for step in data["displaySteps"]] == ["goto", "click"]
    assert data["totalStepsCount"] == 4
    assert data["hiddenStepsCount"] == 2


def test_report_generator_writes_html_and_json(tmp_path):
    task = Task(goal="打开页面", start_url="https://example.com")
    task.logs.append(
        TaskLog(
            step_number=1,
            action="goto",
            url_after="https://example.com",
            screenshot_path=str(tmp_path / "shot.png"),
        )
    )

    generated = ReportGenerator(tmp_path / "reports").generate(task)

    assert generated.html_path.exists()
    assert generated.json_path.exists()
    assert "Argus 黑盒测试报告" in generated.html_path.read_text(encoding="utf-8")


def test_generate_report_safely_keeps_original_task_result():
    class FailingReportGenerator:
        def generate(self, task: Task):
            raise RuntimeError("磁盘不可写")

    task = Task(goal="打开页面")
    task.error_message = "原始失败原因"

    saved = generate_report_safely(task, FailingReportGenerator(), lambda item: item)

    assert saved.report_path is None
    assert "原始失败原因" in saved.error_message
    assert "报告生成失败" in saved.error_message
