from argus_py.report.models import Report
from argus_py.report.serializer import report_to_dict
from argus_py.task.models import Task


def test_report_to_dict():
    report = Report.from_task(Task(goal="打开页面"))
    data = report_to_dict(report)

    assert data["task"]["goal"] == "打开页面"
    assert data["report_id"].startswith("report-")
