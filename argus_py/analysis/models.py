"""分析执行领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from argus_py.analysis.enums import AnalysisRunStatus, CompletenessStatus


@dataclass
class SourceLocation:
    """源码位置 — 结构化数据，推荐替代 file_path + line_number。"""

    file_path: str
    start_line: int
    start_column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    def to_display(self) -> str:
        """人类可读的显示格式。"""
        if not self.file_path:
            return "(unknown)"
        if self.start_line < 1:
            return self.file_path
        # 基础位置：file:start_line
        base = f"{self.file_path}:{self.start_line}"
        # 列号（仅当有值时展示）
        if self.start_column is not None:
            base += f":{self.start_column}"
        # 多行范围
        if self.end_line is not None and self.end_line != self.start_line:
            base += f"-{self.end_line}"
            if self.end_column is not None:
                base += f":{self.end_column}"
        return base


@dataclass
class QualityIssue:
    """结构化质量问题。"""

    code: str
    level: str
    message: str
    affected_count: int | None = None
    total_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "message": self.message,
            "affectedCount": self.affected_count,
            "totalCount": self.total_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityIssue":
        return cls(
            code=data["code"],
            level=data["level"],
            message=data["message"],
            affected_count=data.get("affectedCount"),
            total_count=data.get("totalCount"),
        )


@dataclass
class AnalysisRun:
    """一次白盒分析执行记录 — 不可变结果绑定。"""

    analysis_id: str
    task_id: str
    source_snapshot_id: str
    resolved_commit_sha: str | None = None
    run_status: str = "QUEUED"
    completeness_status: str = "NOT_EVALUATED"
    external_job_id: str | None = None
    external_job_status: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    stop_reason: str | None = None
    result_schema_version: int = 1
    result_digest: str | None = None
    config_json: str | None = None
    raw_result_json: str | None = None
    quality_policy_version: int = 1
    quality_issues: list[QualityIssue] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    projection_completed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def run_status_enum(self) -> AnalysisRunStatus:
        return AnalysisRunStatus(self.run_status)

    @property
    def completeness_status_enum(self) -> CompletenessStatus:
        return CompletenessStatus(self.completeness_status)

    @property
    def is_terminal(self) -> bool:
        return self.run_status_enum.is_terminal


@dataclass
class AnalysisMetrics:
    """分析指标。"""

    eligible_source_files: int = 0
    parsed_source_files: int = 0
    total_calls: int = 0
    resolved_calls: int = 0  # resolved_high + resolved_medium
