"""阶段四：Attempt staging→activate 原子发布测试。

覆盖：staging 写入失败不影响旧 active_attempt；activate 事务原子性；
跨 Run 归属阻断。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.correlation.enums import (
    CorrelationRunStatus,
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
)
from argus_py.correlation.models import (
    EndpointEvidence,
)
from argus_py.task.storage import TaskSQLiteStorage

from tests.integration.correlation._fixtures import (
    setup_base_tables,
    setup_ready_correlation_run,
    setup_request_evidence,
)


def _setup_ready_run(db: Path) -> tuple[TaskSQLiteStorage, str, str]:
    """创建 READY 状态 Run 并认领 Attempt，返回 (storage, cr_id, attempt_id)。"""
    storage = setup_base_tables(db)
    setup_ready_correlation_run(storage)
    setup_request_evidence(storage)

    attempt = storage.claim_and_create_attempt("cr1", "worker-1")
    assert attempt is not None
    return storage, "cr1", attempt.correlation_attempt_id


# ── staging 写入失败不影响旧 active_attempt ────────────────


def test_evidence_inserted_but_not_activated_is_invisible(tmp_path: Path) -> None:
    """staging 写入 EndpointEvidence 但不 activate → API 不返回。"""
    db = tmp_path / "test.db"
    storage, cr_id, attempt_id = _setup_ready_run(db)

    # 写入 evidence（staging）
    ev = EndpointEvidence(
        endpoint_evidence_id="eev-staging",
        correlation_run_id=cr_id,
        correlation_attempt_id=attempt_id,
        request_evidence_id="req1",
        resolution_status=ResolutionStatus.UNIQUE,
        match_strategy=MatchStrategy.EXACT,
        confidence=MatchConfidence.HIGH,
        matched_endpoint_id="ep1",
        candidate_count=1,
        matcher_version="v1",
        normalization_version="v1",
        created_at="2024-01-01",
    )
    storage.insert_endpoint_evidence_batch([ev])

    # staging 写入成功——直接按 attempt_id 查询可见（用于调试/管理）
    items, total = storage.list_endpoint_evidence(attempt_id, resolution_status="UNIQUE")
    assert total >= 1
    assert items[0]["endpoint_evidence_id"] == "eev-staging"

    # 未 activate → active_attempt_id 为 None
    # → API 层（通过 active_attempt_id 查询）不会返回 staging 数据
    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.active_attempt_id is None


def test_activate_alters_active_attempt(tmp_path: Path) -> None:
    """activate 后 active_attempt_id 指向新 Attempt，Run 状态更新。"""
    db = tmp_path / "test.db"
    storage, cr_id, attempt_id = _setup_ready_run(db)

    storage.complete_and_activate_attempt(attempt_id, "SUCCEEDED", completeness="COMPLETE")

    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.active_attempt_id == attempt_id
    assert cr.status == CorrelationRunStatus.SUCCEEDED


def test_activate_partial_sets_run_partial(tmp_path: Path) -> None:
    """PARTIAL attempt → Run 状态为 PARTIAL。"""
    db = tmp_path / "test.db"
    storage, cr_id, attempt_id = _setup_ready_run(db)

    storage.complete_and_activate_attempt(attempt_id, "PARTIAL", completeness="PARTIAL")

    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.status == CorrelationRunStatus.PARTIAL


def test_activate_failed_not_alter_active_attempt(tmp_path: Path) -> None:
    """FAILED attempt 不覆盖已有 active_attempt_id。"""
    db = tmp_path / "test.db"
    storage, cr_id, attempt1_id = _setup_ready_run(db)

    # 先完成一个 SUCCEEDED Attempt 作为旧 active
    storage.complete_and_activate_attempt(attempt1_id, "SUCCEEDED", completeness="COMPLETE")
    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.status == CorrelationRunStatus.SUCCEEDED
    assert cr.active_attempt_id == attempt1_id

    # 手动回退 Run 状态为 READY 并保留 active_attempt_id（模拟重试）
    # 使用公共 API set_correlation_status，它只更新 status 列，
    # active_attempt_id 保持不变
    storage.set_correlation_status(cr_id, "READY")

    # 重试：认领新 Attempt → 不应覆盖 active_attempt_id
    attempt2 = storage.claim_and_create_attempt(cr_id, "worker-2")
    assert attempt2 is not None
    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.active_attempt_id == attempt1_id  # 旧 active 未被 claim 覆盖

    # 新 Attempt 失败 → active_attempt_id 仍为旧 SUCCEEDED
    storage.complete_and_activate_attempt(
        attempt2.correlation_attempt_id, "FAILED", completeness="COMPLETE"
    )
    cr = storage.get_correlation_run(cr_id)
    assert cr is not None
    assert cr.status == CorrelationRunStatus.FAILED
    assert cr.active_attempt_id == attempt1_id  # 旧 active 未被 FAILED 覆盖


# ── 跨 Run 归属阻断 ────────────────────────────────────────


def test_evidence_cross_run_fk_rejected(tmp_path: Path) -> None:
    """EndpointEvidence 的 (correlation_run_id, correlation_attempt_id)
    跨 Run 引用 → IntegrityError。"""
    db = tmp_path / "test.db"
    storage = setup_base_tables(db)
    setup_request_evidence(storage)

    # 创建两个 READY Run，认领第一个
    setup_ready_correlation_run(storage, correlation_run_id="cr-a")
    setup_ready_correlation_run(
        storage,
        correlation_run_id="cr-b",
        desired_snapshot_id="xyz789",
        config_digest="d2",
        analysis_id="analysis-2",
        snapshot_id="xyz789",
        projection_version=2,
    )

    attempt_a = storage.claim_and_create_attempt("cr-a", "w1")
    assert attempt_a is not None

    # 尝试创建 evidence：cr-b + ca-a（跨 Run）
    with pytest.raises(Exception):  # noqa: B017 — FK IntegrityError is the expected cross-run error
        storage.insert_endpoint_evidence_batch(
            [
                EndpointEvidence(
                    endpoint_evidence_id="eev-bad",
                    correlation_run_id="cr-b",
                    correlation_attempt_id=attempt_a.correlation_attempt_id,
                    request_evidence_id="req1",
                    resolution_status=ResolutionStatus.UNIQUE,
                    match_strategy=MatchStrategy.EXACT,
                    confidence=MatchConfidence.HIGH,
                    matched_endpoint_id="ep1",
                    candidate_count=1,
                    matcher_version="v1",
                    normalization_version="v1",
                    created_at="2024-01-01",
                )
            ]
        )
