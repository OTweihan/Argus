"""白盒成功结果持久化（可维护性 M4）。

O-04 抽取为可复用函数：正常执行（WhiteboxRunner.run）与启动恢复
（重新接管已完成结果）共用。时间线事件 / correlation 唤醒不属于本模块，
由调用方决定。

包内模块：runner / recovery 直接 import 公开名；诊断摘要见 ``projection``。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from argus_py.analysis.enums import AnalysisRunStatus
from argus_py.observability.context import run_in_thread
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.models import WhiteboxResult
from argus_py.whitebox.projection import (
    build_diag_summary,
    build_projection_data,
    map_findings,
    serialize_whitebox_result,
)

logger = logging.getLogger(__name__)

__all__ = [
    "find_reusable_analysis_id",
    "persist_success_result",
]


@dataclass(frozen=True)
class _AnalysisPersistPayload:
    """投影持久化所需的派生数据（在 IO 线程一次性计算完成）。"""

    result_digest: str
    issues_json: str
    projection_data: dict[str, Any]


async def _persist_analysis_result(
    lifecycle: TaskLifecycleService,
    analysis_id: str,
    result: WhiteboxResult,
    serialized: dict[str, Any],
    payload_json: str,
) -> None:
    """将 Java 原始结果映射到结构化投影表（方案事务 1 + 2）。

    ``serialized`` / ``payload_json`` 由调用方 ``persist_success_result`` 计算
    一次后传入：同时供 ``result_json`` 与 ``raw_json`` 复用，避免对同一结果
    重复序列化、重复评估完整性（O-07 之后白盒成功路径曾对完整结果做 2 次
    JSON 序列化 + 3 次完整性评估）。

    摘要哈希与全量投影行构造是 CPU/IO 重活（大项目 result_json 可达数十 MB），
    与 DB 写入一并放入 IO 线程执行，避免阻塞事件循环。
    """

    def _prepare_payload() -> _AnalysisPersistPayload:
        issues_json = json.dumps(serialized["qualityIssues"], ensure_ascii=False)
        return _AnalysisPersistPayload(
            result_digest=sha256(payload_json.encode()).hexdigest(),
            issues_json=issues_json,
            projection_data=build_projection_data(result, analysis_id=analysis_id),
        )

    payload = await run_in_thread(_prepare_payload)

    # 完整性结论已随 serialized 一次性计算，直接取用。
    completeness = serialized["completeness"]

    # 事务 1：独立持久化 Java 原始响应（审计留存）
    await run_in_thread(
        lifecycle.save_analysis_raw_result,
        analysis_id,
        payload_json,
        payload.result_digest,
    )

    # 事务 2：投影写入 + 标记 SUCCEEDED
    await run_in_thread(
        lifecycle.complete_analysis_projection,
        analysis_id,
        completeness=completeness,
        quality_issues_json=payload.issues_json,
        result_digest=payload.result_digest,
        projection_data=payload.projection_data,
    )


@dataclass(frozen=True)
class _SuccessResultPayload:
    """成功结果落盘所需的任务字段值（在 IO 线程一次性计算完成）。"""

    findings: list[Any]
    result_summary: str
    serialized: dict[str, Any]
    payload_json: str


def _prepare_success_result(
    result: WhiteboxResult,
    *,
    analysis_id: str,
    source_root: str | None,
    scope: str,
) -> _SuccessResultPayload:
    """同步准备成功结果的任务字段与序列化产物（仅限 IO 线程调用）。

    ``map_findings`` 对每条 finding 做一次 ``Path.resolve()``（文件系统 IO）、
    ``serialize_whitebox_result`` 构建含全部调用图明细的巨型 dict、
    ``json.dumps`` 序列化可达数十 MB——全部属于不应出现在事件循环上的重活。
    """
    findings = map_findings(
        result.findings,
        source_root=source_root,
        analysis_id=analysis_id,
    )
    diag_summary = build_diag_summary(result.diagnostics)
    endpoint_count = len(result.endpoints)
    finding_count = len(result.findings)
    result_summary = (
        f"白盒分析完成。发现 {endpoint_count} 个端点、"
        f"{finding_count} 个代码缺陷/坏味道。"
        f"{diag_summary}"
    )
    serialized = serialize_whitebox_result(result, endpoint_count, finding_count, scope)
    payload_json = json.dumps(serialized, ensure_ascii=False)
    return _SuccessResultPayload(
        findings=findings,
        result_summary=result_summary,
        serialized=serialized,
        payload_json=payload_json,
    )


async def persist_success_result(
    lifecycle: TaskLifecycleService,
    task: Task,
    result: WhiteboxResult,
    *,
    analysis_id: str,
    source_root: str | None = None,
    scope: str = "",
) -> None:
    """把成功结果落盘到 task 与投影表。

    O-04 抽取为可复用函数：正常执行（WhiteboxRunner.run）与启动恢复
    （重新接管已完成结果）共用。时间线事件 / correlation 唤醒不属于本函数，
    由调用方决定。
    """
    prepared = await run_in_thread(
        _prepare_success_result,
        result,
        analysis_id=analysis_id,
        source_root=source_root,
        scope=scope,
    )
    task.findings = prepared.findings
    task.result_summary = prepared.result_summary
    task.result_json = prepared.payload_json
    task.result_schema_version = 1
    task.result_size_bytes = len(task.result_json)
    task.external_job_status = "SUCCEEDED"

    await run_in_thread(lifecycle.save_task_findings, task)
    await _persist_analysis_result(
        lifecycle, analysis_id, result, prepared.serialized, task.result_json
    )


def find_reusable_analysis_id(storage: TaskSQLiteStorage, task_id: str) -> str | None:
    """返回任务最近的非终态 analysis_run 的 analysis_id（O-04 重新接管）。

    恢复路径与 WhiteboxRunner.run 共用：worker 崩溃后重新接管同一 run。
    """
    try:
        runs, _ = storage.list_analysis_runs(task_id)
    except Exception:
        logger.exception("读取 analysis_run 失败: task_id=%s", task_id)
        return None
    for run in runs:
        if run.run_status in {
            AnalysisRunStatus.QUEUED.value,
            AnalysisRunStatus.SUBMITTING.value,
            AnalysisRunStatus.RUNNING.value,
            AnalysisRunStatus.STOPPED_WAITING.value,
        }:
            return run.analysis_id
    return None
