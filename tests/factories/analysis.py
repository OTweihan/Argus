"""测试工厂 — 白盒分析相关实体。"""

from __future__ import annotations

from typing import Any

from argus_py.analysis.models import AnalysisRun, QualityIssue


def make_analysis_run(
    analysis_id: str = "analysis-1",
    task_id: str = "t-1",
    source_snapshot_id: str = "abc123",
    resolved_commit_sha: str | None = None,
    result_schema_version: int = 1,
    config_json: str = "{}",
    run_status: str = "PENDING",
    completeness_status: str = "NOT_EVALUATED",
    quality_issues: list[QualityIssue] | None = None,
    **overrides,
) -> AnalysisRun:
    """创建最小化 AnalysisRun。"""
    return AnalysisRun(
        analysis_id=analysis_id,
        task_id=task_id,
        source_snapshot_id=source_snapshot_id,
        resolved_commit_sha=resolved_commit_sha,
        result_schema_version=result_schema_version,
        config_json=config_json,
        run_status=run_status,
        completeness_status=completeness_status,
        quality_issues=quality_issues or [],
        **overrides,
    )


def make_endpoint_dict(
    endpoint_id: str = "ep-1",
    http_method: str = "GET",
    normalized_path_template: str = "/api/users",
    is_templated: bool = False,
    static_prefix: str = "",
    controller_class: str = "com.example.TestController",
    controller_method: str = "testMethod",
    path_segment_count: int | None = None,
    **overrides,
) -> dict[str, Any]:
    """创建最小化 endpoint dict，用于 EndpointMatcher 测试。

    默认 generate 精确（非模板）端点。
    """
    if path_segment_count is None:
        path_segment_count = len([s for s in normalized_path_template.strip("/").split("/") if s])

    ep: dict[str, Any] = {
        "endpoint_id": endpoint_id,
        "http_method": http_method,
        "normalized_exact_path": "" if is_templated else normalized_path_template,
        "normalized_path_template": normalized_path_template,
        "is_templated": is_templated,
        "path_segment_count": path_segment_count,
        "static_prefix": static_prefix,
        "controller_class": controller_class,
        "controller_method": controller_method,
    }
    ep.update(overrides)
    return ep
