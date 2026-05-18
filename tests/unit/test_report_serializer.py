from argus_py.report.generator import ReportGenerator, generate_report_safely
from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict
from argus_py.task.models import Task, TaskLog


def test_report_to_dict():
    report = Report.from_task(Task(goal="打开页面"))
    data = report_to_dict(report)

    assert data["task"]["goal"] == "打开页面"
    assert data["reportId"].startswith("report-")


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
