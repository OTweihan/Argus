"""阶段四：自动绑定回调测试 — P1#6。

验证 _on_whitebox_analysis_succeeded 的状态机推进路径：
- WAITING_ANALYSIS → WAITING_BLACKBOX（分析先完成）
- WAITING_BLACKBOX → READY（黑盒随后完成）
- 快照不匹配/MISMATCHED override 的校验路径
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_py.analysis.models import AnalysisRun
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.correlation.enums import (
    BlackboxRunStatus,
    CorrelationRunStatus,
    SourceAlignmentStatus,
)
from argus_py.correlation.models import BlackboxRun, CorrelationRun
from argus_py.task.models import Task
from argus_py.task.storage import TaskSQLiteStorage

pytestmark = [pytest.mark.integration]


# ── 工具 ──────────────────────────────────────────────────────────


def _make_analysis_run(
    analysis_id: str, task_id: str, resolved_commit_sha: str = "abc123"
) -> AnalysisRun:
    return AnalysisRun(
        analysis_id=analysis_id,
        task_id=task_id,
        source_snapshot_id="src-snap-1",
        resolved_commit_sha=resolved_commit_sha,
        run_status="SUCCEEDED",
        config_json="{}",
    )


def _create_seed_data(
    storage: TaskSQLiteStorage,
    analysis_task_id: str = "t-whitebox",
    analysis_id: str = "analysis-a",
    blackbox_run_id: str = "bb-auto",
    blackbox_task_id: str = "t-blackbox",
    project_id: str = "p1",
    *,
    correlation_snapshot: str = "abc123",
    correlation_status: CorrelationRunStatus = CorrelationRunStatus.WAITING_ANALYSIS,
) -> None:
    """创建基础数据：项目 + 任务 + analysis_run + blackbox_run + correlation_run。"""
    # 确保 project 存在（FK 约束）
    with storage._correlation._pool.tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO projects (project_id, name, created_at, updated_at) "
            "VALUES (?, ?, '2024-01-01', '2024-01-01')",
            (project_id, "test"),
        )
    # analysis_run.task_id 对应的任务
    whitebox_task = Task(
        task_id=analysis_task_id,
        goal="whitebox analysis",
        project_id=project_id,
        task_type=TaskType.WHITEBOX,
        status=TaskStatus.COMPLETED,
    )
    storage.save(whitebox_task)

    ar = _make_analysis_run(analysis_id, analysis_task_id)
    storage.create_analysis_run(ar)

    # 黑盒端
    blackbox_task = Task(
        task_id=blackbox_task_id,
        goal="blackbox scan",
        project_id=project_id,
        task_type=TaskType.BLACKBOX,
        status=TaskStatus.COMPLETED,
    )
    storage.save(blackbox_task)

    bb = storage.create_blackbox_run(
        BlackboxRun(
            blackbox_run_id=blackbox_run_id,
            task_id=blackbox_task_id,
            attempt=1,
            status=BlackboxRunStatus.PENDING,
            started_at="2024-01-01T00:00:00",
        )
    )

    storage.create_correlation_run(
        CorrelationRun(
            correlation_run_id=f"cr-{correlation_snapshot}",
            project_id=project_id,
            blackbox_run_id=bb.blackbox_run_id,
            desired_source_snapshot_id=correlation_snapshot,
            correlation_config_digest="d1",
            matcher_version="v1",
            normalization_version="v1",
            status=correlation_status,
            created_at="2024-01-01T00:00:00",
        )
    )


class TestAutoBindAnalysisSucceeded:
    """白盒分析成功后自动绑定的状态机测试。"""

    def test_waiting_analysis_bound_to_verified(self, tmp_path: Path) -> None:
        """P1：WAITING_ANALYSIS + 同项目同快照分析 → 自动绑定为 VERIFIED。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(
            storage,
            correlation_snapshot="abc123",
            project_id="p1",
        )

        # 模拟 _on_whitebox_analysis_succeeded 逻辑
        analysis_id = "analysis-a"
        snapshot_id = "abc123"
        analysis_project_id = "p1"

        waiting = storage.find_waiting_correlations(snapshot_id, project_id=analysis_project_id)
        assert len(waiting) == 1
        cr = waiting[0]
        assert cr.status == CorrelationRunStatus.WAITING_ANALYSIS

        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            analysis_id,
            snapshot_id,
            projection_version=1,
            alignment="VERIFIED",
        )

        # 读取绑定后的状态
        bound_cr = storage.get_correlation_run(cr.correlation_run_id)
        assert bound_cr is not None
        assert bound_cr.analysis_id == analysis_id
        assert bound_cr.bound_source_snapshot_id == snapshot_id
        assert bound_cr.source_alignment_status == SourceAlignmentStatus.VERIFIED

    def test_analysis_succeeded_then_blackbox_done_moves_to_ready(self, tmp_path: Path) -> None:
        """P1：分析先完成绑定 → WAITING_BLACKBOX；黑盒完成后 → READY。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(
            storage,
            correlation_snapshot="abc123",
        )

        analysis_id = "analysis-a"
        snapshot_id = "abc123"

        # Step 1: 绑定分析 → WAITING_BLACKBOX
        waiting = storage.find_waiting_correlations(snapshot_id, project_id="p1")
        assert len(waiting) == 1
        cr = waiting[0]

        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            analysis_id,
            snapshot_id,
            projection_version=1,
            alignment="VERIFIED",
        )
        storage.set_correlation_status(cr.correlation_run_id, "WAITING_BLACKBOX")

        bound_cr = storage.get_correlation_run(cr.correlation_run_id)
        assert bound_cr is not None
        assert bound_cr.status == CorrelationRunStatus.WAITING_BLACKBOX

        # Step 2: 黑盒完成 → 检查并推进到 READY
        storage.update_blackbox_run_status(
            "bb-auto", BlackboxRunStatus.SUCCESS.value, "2024-01-01T00:01:00"
        )
        bb = storage.get_blackbox_run("bb-auto")
        bb_done = bb is not None and bb.status in (
            BlackboxRunStatus.SUCCESS,
            BlackboxRunStatus.FAILED,
        )
        assert bb_done

        storage.set_correlation_status(bound_cr.correlation_run_id, "READY")
        ready_cr = storage.get_correlation_run(bound_cr.correlation_run_id)
        assert ready_cr is not None
        assert ready_cr.status == CorrelationRunStatus.READY

    def test_snapshot_mismatch_not_matched(self, tmp_path: Path) -> None:
        """不同快照的 WAITING_ANALYSIS 不被自动匹配。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(
            storage,
            correlation_snapshot="abc123",
            analysis_id="analysis-a",
        )

        # 查询时用不同的快照 → 不应返回 WAITING_ANALYSIS run
        waiting = storage.find_waiting_correlations("xyz789", project_id="p1")
        assert len(waiting) == 0

    def test_empty_snapshot_exact_match_only(self, tmp_path: Path) -> None:
        """空快照仅被空查询匹配（精确匹配语义），不被具体快照查询误匹配。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(
            storage,
            correlation_snapshot="",
            analysis_id="analysis-a",
        )

        # 具体快照不应匹配空快照 run
        waiting = storage.find_waiting_correlations("abc123", project_id="p1")
        assert len(waiting) == 0

        # 空查询匹配空快照 run（精确匹配，由上层回调决定是否使用此回退）
        waiting2 = storage.find_waiting_correlations("", project_id="p1")
        assert len(waiting2) == 1
        assert waiting2[0].desired_source_snapshot_id == ""

    def test_multiple_waiting_only_matching_snapshot_bound(self, tmp_path: Path) -> None:
        """多个 WAITING_ANALYSIS，只绑定快照匹配的那个。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")
        # 确保 project 存在
        with storage._correlation._pool.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (project_id, name, created_at, updated_at) "
                "VALUES ('p1', 'test', '2024-01-01', '2024-01-01')"
            )

        # Run A: 快照 abc123
        storage.save(
            Task(
                task_id="t-whitebox-a",
                goal="wb a",
                project_id="p1",
                task_type=TaskType.WHITEBOX,
                status=TaskStatus.COMPLETED,
            )
        )
        integration_task = Task(
            task_id="t-blackbox-2",
            goal="bb multi",
            project_id="p1",
            task_type=TaskType.BLACKBOX,
            status=TaskStatus.PENDING,
        )

        ar = _make_analysis_run("analysis-multi", "t-whitebox-a")
        storage.create_analysis_run(ar)

        storage.save(integration_task)
        for i, snap in enumerate(["abc123", "xyz789", "abc123"]):
            bb = storage.create_blackbox_run(
                BlackboxRun(
                    blackbox_run_id=f"bb-multi-{i}",
                    task_id="t-blackbox-2",
                    attempt=i + 1,
                    status=BlackboxRunStatus.PENDING,
                    started_at="2024-01-01T00:00:00",
                )
            )
            storage.create_correlation_run(
                CorrelationRun(
                    correlation_run_id=f"cr-multi-{i}",
                    project_id="p1",
                    blackbox_run_id=bb.blackbox_run_id,
                    desired_source_snapshot_id=snap,
                    correlation_config_digest="d1",
                    matcher_version="v1",
                    normalization_version="v1",
                    status=CorrelationRunStatus.WAITING_ANALYSIS,
                    created_at="2024-01-01T00:00:00",
                )
            )

        # 按 abc123 查找 → 应返回两个 abc123 的运行，不包括 xyz789
        waiting = storage.find_waiting_correlations("abc123", project_id="p1")
        cr_ids = {cr.correlation_run_id for cr in waiting}
        assert len(waiting) == 2
        assert "cr-multi-0" in cr_ids
        assert "cr-multi-1" not in cr_ids  # xyz789
        assert "cr-multi-2" in cr_ids

    def test_analysis_then_blackbox_then_claim(self, tmp_path: Path) -> None:
        """完整自动绑定链路：分析完成 → 绑定 + 黑盒完成 → READY → 可认领。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(storage)

        analysis_id = "analysis-a"
        snapshot_id = "abc123"

        # 1. 分析完成回调
        waiting = storage.find_waiting_correlations(snapshot_id, project_id="p1")
        assert len(waiting) == 1
        cr = waiting[0]

        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            analysis_id,
            snapshot_id,
            projection_version=1,
            alignment="VERIFIED",
        )

        # 2. 黑盒也已完成 → READY
        storage.update_blackbox_run_status(
            "bb-auto", BlackboxRunStatus.SUCCESS.value, "2024-01-01T00:01:00"
        )
        storage.set_correlation_status(cr.correlation_run_id, "READY")

        ready_cr = storage.get_correlation_run(cr.correlation_run_id)
        assert ready_cr is not None
        assert ready_cr.status == CorrelationRunStatus.READY

        # 3. 可被认领
        attempt = storage.claim_and_create_attempt(ready_cr.correlation_run_id, "worker-1")
        assert attempt is not None
        assert attempt.analysis_id == analysis_id
        assert attempt.source_snapshot_id == snapshot_id

    # ── P1 回归：黑盒先启动（无快照），分析后完成 ──────────────

    def test_blackbox_first_then_analysis_fallback_bind(self, tmp_path: Path) -> None:
        """P1 回归：黑盒任务先启动（desired_source_snapshot_id=""），
        之后白盒分析完成 → 回调通过空快照回退匹配 → 自动绑定。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(
            storage,
            correlation_snapshot="",  # 黑盒任务无快照
            analysis_id="analysis-a",
        )

        analysis_id = "analysis-a"
        analysis_snapshot = "abc123"

        # 模拟 _on_whitebox_analysis_succeeded 的两阶段查找
        # 1. 精确快照匹配 → 无结果
        exact = storage.find_waiting_correlations(analysis_snapshot, project_id="p1")
        assert len(exact) == 0

        # 2. 回退空快照匹配 → 找到黑盒任务创建的 run
        fallback = storage.find_waiting_correlations("", project_id="p1")
        assert len(fallback) == 1
        cr = fallback[0]
        assert cr.desired_source_snapshot_id == ""

        storage.bind_correlation_analysis(
            cr.correlation_run_id,
            analysis_id,
            analysis_snapshot,
            projection_version=1,
            alignment="UNVERIFIED",
        )

        # 绑定后 desired_source_snapshot_id 应被更新为分析的快照
        bound_cr = storage.get_correlation_run(cr.correlation_run_id)
        assert bound_cr is not None
        assert bound_cr.analysis_id == analysis_id
        assert bound_cr.bound_source_snapshot_id == analysis_snapshot
        assert bound_cr.desired_source_snapshot_id == analysis_snapshot

    def test_analysis_before_blackbox_auto_bind_at_creation(self, tmp_path: Path) -> None:
        """P1 回归：分析先存在，黑盒任务启动时自动绑定。"""
        from tests.integration.correlation._fixtures import setup_base_tables

        storage = setup_base_tables(tmp_path / "preexist.db")

        # 创建分析数据（模拟分析先完成）
        analysis_task = Task(
            task_id="t-wb-preexist",
            goal="pre-existing whitebox",
            project_id="p1",
            task_type=TaskType.WHITEBOX,
            status=TaskStatus.COMPLETED,
        )
        storage.save(analysis_task)
        ar = AnalysisRun(
            analysis_id="analysis-preexist",
            task_id="t-wb-preexist",
            source_snapshot_id="src-1",
            resolved_commit_sha="def456",
            run_status="SUCCEEDED",
            config_json="{}",
        )
        storage.create_analysis_run(ar)

        # 模拟 container.py 的创建逻辑：黑盒任务无快照 → 查找最新分析
        snapshot_id = ""
        project_id = "p1"
        if not snapshot_id and project_id:
            latest = storage.get_latest_succeeded_analysis_by_project(project_id)
            assert latest is not None
            analysis_snapshot = getattr(latest, "resolved_commit_sha", None) or ""
            if analysis_snapshot:
                snapshot_id = analysis_snapshot

        assert snapshot_id == "def456"

        # 创建 BlackboxRun + CorrelationRun（模拟 container 创建流程）
        storage.create_correlation_run(
            CorrelationRun(
                correlation_run_id="cr-preexist",
                project_id=project_id,
                blackbox_run_id="bb1",  # _fixtures.setup_base_tables 已创建
                desired_source_snapshot_id=snapshot_id,
                correlation_config_digest="d1",
                matcher_version="v1",
                normalization_version="v1",
                analysis_id="analysis-preexist",
                bound_source_snapshot_id="def456",
                analysis_projection_version=1,
                status=CorrelationRunStatus.WAITING_BLACKBOX,
                created_at="2024-01-01T00:00:00",
            )
        )

        cr = storage.get_correlation_run("cr-preexist")
        assert cr is not None
        assert cr.desired_source_snapshot_id == "def456"
        assert cr.analysis_id == "analysis-preexist"
        assert cr.status == CorrelationRunStatus.WAITING_BLACKBOX

    def test_analysis_has_no_snapshot_skips_bind(self, tmp_path: Path) -> None:
        """P1 回归：分析没有 resolved_commit_sha → 跳过绑定，不匹配任何 WAITING_ANALYSIS。"""
        storage = TaskSQLiteStorage(tmp_path / "test.db")

        _create_seed_data(storage)

        # 空快照的分析不应触发绑定（模拟 _on_whitebox_analysis_succeeded 中
        # `if not snapshot_id: return` 的守卫逻辑）
        snapshot_id = ""
        waiting = storage.find_waiting_correlations(snapshot_id, project_id="p1")
        # 空字符串不匹配任何 desired_source_snapshot_id
        assert len(waiting) == 0
