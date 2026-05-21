"""SQLite 行 ↔ 领域模型双向映射。"""

from __future__ import annotations

import json
from typing import Any

from argus_py.core.constants import utc_now
from argus_py.task.models import Finding, Task, TaskLog


def task_to_row(task: Task) -> tuple[Any, ...]:
    """将 Task 实体转换为 SQLite INSERT 参数。"""
    return (
        task.task_id,
        task.goal,
        task.name,
        task.start_url,
        task.task_type.value,
        task.status.value,
        task.project_id,
        task.max_steps,
        task.timeout_seconds,
        1 if task.capture_screenshots else 0,
        task.current_step,
        json.dumps(task.parameters, ensure_ascii=False),
        task.created_at.isoformat(),
        task.started_at.isoformat() if task.started_at else None,
        task.completed_at.isoformat() if task.completed_at else None,
        task.report_path,
        task.result_summary,
        task.error_message,
    )


def log_to_row(task_id: str, log: TaskLog) -> tuple[Any, ...]:
    """将 TaskLog 实体转换为 SQLite INSERT 参数。"""
    return (
        log.task_log_id,
        task_id,
        log.step_number,
        log.action,
        log.result.value,
        json.dumps(log.params, ensure_ascii=False),
        log.url_before,
        log.url_after,
        log.screenshot_path,
        log.message,
        log.error,
        log.error_code,
        log.created_at.isoformat(),
    )


def finding_to_row(task_id: str, finding: Finding) -> tuple[Any, ...]:
    """将 Finding 实体转换为 SQLite INSERT 参数。"""
    return (
        finding.finding_id,
        task_id,
        finding.title,
        finding.description,
        finding.severity.value,
        finding.finding_type.value,
        finding.url,
        finding.location,
        finding.screenshot_path,
        finding.created_at.isoformat(),
    )


def row_to_event(row: Any) -> Any:
    """将 SQLite 行还原为 TimelineEvent。"""
    from argus_py.task.event import TimelineEvent as TE
    from argus_py.task.models import _parse_datetime

    return TE(
        event_id=row["event_id"],
        task_id=row["task_id"],
        event_type=row["event_type"],
        phase=row["phase"],
        step_number=row["step_number"],
        summary=row["summary"],
        data=json.loads(row["data_json"] or "{}"),
        created_at=_parse_datetime(row["created_at"]) or utc_now(),
    )


def row_to_task(
    task_row: Any,
    log_rows: list[Any],
    finding_rows: list[Any],
) -> Task:
    """将 SQLite 行还原为 Task 实体。"""
    from argus_py.core.enums import TaskStatus, TaskType
    from argus_py.task.models import _parse_datetime

    return Task(
        task_id=task_row["task_id"],
        goal=task_row["goal"],
        name=task_row["name"],
        start_url=task_row["start_url"],
        task_type=TaskType(task_row["task_type"]),
        status=TaskStatus(task_row["status"]),
        project_id=task_row["project_id"],
        max_steps=task_row["max_steps"],
        timeout_seconds=task_row["timeout_seconds"],
        capture_screenshots=bool(task_row["capture_screenshots"]),
        parameters=json.loads(task_row["parameters_json"] or "{}"),
        logs=[row_to_log(r) for r in log_rows],
        findings=[row_to_finding(r) for r in finding_rows],
        created_at=_parse_datetime(task_row["created_at"]) or utc_now(),
        started_at=_parse_datetime(task_row["started_at"]),
        completed_at=_parse_datetime(task_row["completed_at"]),
        report_path=task_row["report_path"],
        result_summary=task_row["result_summary"],
        error_message=task_row["error_message"],
    )


def row_to_log(row: Any) -> TaskLog:
    """将 SQLite 行还原为 TaskLog 实体。"""
    from argus_py.core.enums import StepResult
    from argus_py.task.models import _parse_datetime

    return TaskLog(
        task_log_id=row["task_log_id"],
        step_number=row["step_number"],
        action=row["action"],
        result=StepResult(row["result"]),
        params=json.loads(row["params_json"] or "{}"),
        url_before=row["url_before"],
        url_after=row["url_after"],
        screenshot_path=row["screenshot_path"],
        message=row["message"],
        error=row["error"],
        error_code=row["error_code"],
        created_at=_parse_datetime(row["created_at"]) or utc_now(),
    )


def row_to_finding(row: Any) -> Finding:
    """将 SQLite 行还原为 Finding 实体。"""
    from argus_py.core.enums import FindingSeverity, FindingType
    from argus_py.task.models import _parse_datetime

    return Finding(
        finding_id=row["finding_id"],
        title=row["title"],
        description=row["description"],
        severity=FindingSeverity(row["severity"]),
        finding_type=FindingType(row["finding_type"]),
        url=row["url"],
        location=row["location"],
        screenshot_path=row["screenshot_path"],
        created_at=_parse_datetime(row["created_at"]) or utc_now(),
    )
