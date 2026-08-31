"""回归闭环集成测试：用例 → 批次 → 终态推进 → 差异/门禁/基线。

覆盖回归计划 §6 验收场景：全部通过、子任务失败、新增高危阻断、
无基线首跑、队列满载 fail-fast、崩溃恢复。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest
from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.core.exceptions import ArgusError
from argus_py.infra.queue import TaskQueue
from argus_py.observability import aspect
from argus_py.regression.application import RegressionError, RegressionService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Finding
from argus_py.task.storage import TaskSQLiteStorage
from tests.helpers.factories import AppStack, make_app_stack

BASE_URL = "http://localhost:8765"


@pytest.fixture
def stack(tmp_path: Path) -> AppStack:
    return make_app_stack(tmp_path)


@pytest.fixture
def small_queue_stack(tmp_path: Path) -> AppStack:
    return make_app_stack(tmp_path, queue_max_size=1)


async def _make_project(stack: AppStack) -> str:
    # create_project 是同步方法（路由层经 run_in_thread 调用）
    project = stack.project_service.create_project(name="回归项目", base_url=BASE_URL)
    return project.project_id


def _blackbox_input(goal: str = "验证登录功能", **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": f"用例-{goal[:10]}",
        "taskType": "blackbox",
        "goal": goal,
        "startUrl": f"{BASE_URL}/login",
        "maxSteps": 5,
        "timeoutSeconds": 60,
        "captureScreenshots": False,
        "parameters": {},
        "enabled": True,
        "displayOrder": 0,
    }
    data.update(overrides)
    return data


def _finish_task(
    stack: AppStack,
    task_id: str,
    *,
    findings: list[tuple[str, str]] | None = None,
    fail_message: str | None = None,
) -> None:
    """模拟 Worker 执行：PENDING → RUNNING → 终态（触发回归终态回调）。"""
    task = stack.reader.get_task(task_id)
    stack.lifecycle.start_task(task)
    for title, severity in findings or []:
        finding = Finding(
            title=title,
            description="集成测试发现项",
            severity=FindingSeverity(severity),
            finding_type=FindingType.FUNCTIONAL,
        )
        stack.reader.storage.insert_findings_batch(task_id, [finding])
    latest = stack.reader.get_task(task_id)
    if fail_message is not None:
        stack.lifecycle.fail_task(latest, fail_message)
    else:
        stack.lifecycle.complete_task(latest)


class TestCaseCrud:
    async def test_create_and_list_case_resolves_inputs(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        case = stack.regression.create_case(pid, _blackbox_input())
        assert case.case_id.startswith("regcase-")
        assert case.max_steps == 5
        assert case.timeout_seconds == 60
        # startUrl 与项目 baseUrl 同源，校验通过并原样保存
        assert case.start_url == f"{BASE_URL}/login"
        assert case.capture_screenshots is False

        cases = stack.regression.list_cases(pid)
        assert [c.case_id for c in cases] == [case.case_id]

    async def test_invalid_goal_rejected(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        with pytest.raises(RegressionError) as exc_info:
            stack.regression.create_case(pid, _blackbox_input(goal="   "))
        assert exc_info.value.code == "REGRESSION_INVALID_INPUT"

    async def test_missing_start_url_rejected_without_project_base(self, stack: AppStack) -> None:
        project = stack.project_service.create_project(name="无地址项目")
        with pytest.raises(ArgusError):
            stack.regression.create_case(project.project_id, _blackbox_input(startUrl=None))

    async def test_update_revalidates_and_delete(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        case = stack.regression.create_case(pid, _blackbox_input())
        updated = stack.regression.update_case(
            case.case_id, {"goal": "验证登出功能", "displayOrder": 3}
        )
        assert updated.goal == "验证登出功能"
        assert updated.display_order == 3

        stack.regression.delete_case(case.case_id)
        assert stack.regression.list_cases(pid) == []
        with pytest.raises(RegressionError) as exc_info:
            stack.regression.get_case(case.case_id)
        assert exc_info.value.code == "REGRESSION_CASE_NOT_FOUND"

    async def test_whitebox_case_via_parameters(self, stack: AppStack, tmp_path: Path) -> None:
        pid = await _make_project(stack)
        src = tmp_path / "src"
        src.mkdir()
        case = stack.regression.create_case(
            pid,
            {
                "name": "白盒用例",
                "taskType": "whitebox",
                "goal": "白盒分析",
                "parameters": {
                    "source_type": "local",
                    "source_path": str(src),
                    "scope": "endpoints",
                },
            },
        )
        assert case.task_type.value == "whitebox"
        assert case.whitebox_config_json is not None
        snapshot_params = case.resolved_parameters()
        assert snapshot_params["scope"] == "endpoints"


class TestRunLifecycle:
    async def test_create_run_without_cases_raises(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        with pytest.raises(RegressionError) as exc_info:
            await stack.regression.create_run(pid)
        assert exc_info.value.code == "REGRESSION_NO_ENABLED_CASES"

    async def test_first_run_all_completed_gate_passed_no_baseline(self, stack: AppStack) -> None:
        """验收场景：无基线首跑，全部成功 → gate=passed。"""
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input("用例一"))
        stack.regression.create_case(pid, _blackbox_input("用例二", displayOrder=1))

        run = await stack.regression.create_run(pid, trigger_source="cli")
        assert run.status.value == "running"
        assert run.baseline_run_id is None

        items = stack.regression.get_run_items(run.run_id)
        assert len(items) == 2
        task_ids = [it["taskId"] for it in items]
        assert all(task_ids)

        for tid in task_ids:
            task = stack.reader.get_task(tid)
            assert task.name is not None
            assert task.name.startswith("[回归]")
            # 子任务携带回归关联标识（任务列表跳转用）
            assert task.parameters["regression"]["runId"] == run.run_id
            _finish_task(stack, tid)

        finished = stack.regression.get_run(run.run_id)
        assert finished.gate_result is not None
        assert finished.status.value == "completed"
        assert finished.gate_result.value == "passed"
        summary = stack.regression.get_run_summary(run.run_id)
        assert summary["itemCounts"]["completed"] == 2
        assert summary["findingTotals"]["current"] == 0
        assert summary["diff"]["addedCount"] == 0
        assert summary["blockingReasons"] == []

    async def test_failed_subtask_blocks_gate(self, stack: AppStack) -> None:
        """验收场景：子任务失败 → 批次完成但门禁失败。"""
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())

        run = await stack.regression.create_run(pid)
        (item,) = stack.regression.get_run_items(run.run_id)
        _finish_task(stack, item["taskId"], fail_message="浏览器崩溃")

        finished = stack.regression.get_run(run.run_id)
        assert finished.gate_result is not None
        assert finished.status.value == "completed"
        assert finished.gate_result.value == "failed"
        reasons = stack.regression.get_run_summary(run.run_id)["blockingReasons"]
        assert any("未成功" in r for r in reasons)

    async def test_baseline_diff_added_high_blocks_then_resolved_passes(
        self, stack: AppStack
    ) -> None:
        """验收场景：基线 → 新增高危阻断 → 修复后已解决、门禁通过。"""
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())

        # 第一轮：干净通过并设为基线
        run1 = await stack.regression.create_run(pid)
        (item1,) = stack.regression.get_run_items(run1.run_id)
        _finish_task(stack, item1["taskId"])
        baseline_run = stack.regression.set_baseline(run1.run_id)
        assert baseline_run.is_baseline is True
        baseline1 = stack.regression.get_baseline(pid)
        assert baseline1 is not None
        assert baseline1.run_id == run1.run_id

        # 第二轮：新增一个 high 问题 → 门禁失败；批次创建时固定对比基线
        run2 = await stack.regression.create_run(pid)
        assert run2.baseline_run_id == run1.run_id
        (item2,) = stack.regression.get_run_items(run2.run_id)
        _finish_task(stack, item2["taskId"], findings=[("订单金额显示为 0", "high")])

        finished2 = stack.regression.get_run(run2.run_id)
        assert finished2.gate_result is not None
        assert finished2.gate_result.value == "failed"
        summary2 = stack.regression.get_run_summary(run2.run_id)
        assert summary2["diff"]["addedCount"] == 1
        added = summary2["diff"]["added"][0]
        assert added["title"] == "订单金额显示为 0"
        assert added["severity"] == "high"
        # 基线中该用例没有任何发现项 → 新增条目无基线侧任务
        assert added["baselineTaskId"] is None
        assert added["currentTaskId"] == item2["taskId"]
        assert any("订单金额" in r for r in summary2["blockingReasons"])

        # 第三轮：把失败批次设为新基线（含该高危问题），修复后重跑 →
        # 问题"已解决"，门禁重新通过
        stack.regression.set_baseline(run2.run_id)
        baseline2 = stack.regression.get_baseline(pid)
        assert baseline2 is not None
        assert baseline2.run_id == run2.run_id
        run3 = await stack.regression.create_run(pid)
        assert run3.baseline_run_id == run2.run_id
        (item3,) = stack.regression.get_run_items(run3.run_id)
        _finish_task(stack, item3["taskId"])

        finished3 = stack.regression.get_run(run3.run_id)
        assert finished3.gate_result is not None
        assert finished3.gate_result.value == "passed"
        summary3 = stack.regression.get_run_summary(run3.run_id)
        assert summary3["diff"]["resolvedCount"] == 1
        assert summary3["diff"]["addedCount"] == 0

    async def test_baseline_switch_keeps_single_row(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())
        runs = []
        for _ in range(2):
            run = await stack.regression.create_run(pid)
            (item,) = stack.regression.get_run_items(run.run_id)
            _finish_task(stack, item["taskId"])
            runs.append(stack.regression.get_run(run.run_id))

        stack.regression.set_baseline(runs[0].run_id)
        stack.regression.set_baseline(runs[1].run_id)
        baseline = stack.regression.get_baseline(pid)
        assert baseline is not None
        assert baseline.run_id == runs[1].run_id

        storage: TaskSQLiteStorage = stack.reader.storage
        with storage._regression._pool.ro_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM regression_runs WHERE is_baseline = 1"
            ).fetchone()["cnt"]
        assert count == 1

    async def test_set_baseline_rejected_for_running_run(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())
        run = await stack.regression.create_run(pid)
        with pytest.raises(RegressionError) as exc_info:
            stack.regression.set_baseline(run.run_id)
        assert exc_info.value.code == "BASELINE_ONLY_COMPLETED_BATCH"

    async def test_cancel_run_marks_cancelled(
        self, stack: AppStack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())
        run = await stack.regression.create_run(pid)

        event_loop_thread = threading.get_ident()
        cancel_threads: list[int] = []
        original_cancel = stack.lifecycle.cancel_task

        def recording_cancel(task):
            cancel_threads.append(threading.get_ident())
            return original_cancel(task)

        monkeypatch.setattr(stack.lifecycle, "cancel_task", recording_cancel)

        cancelled = await stack.regression.cancel_run(run.run_id)
        assert cancelled.status.value == "cancelled"
        assert cancel_threads
        assert all(thread_id != event_loop_thread for thread_id in cancel_threads)

        # 子任务被取消且批次项镜像 cancelled → 终态回调不再改写批次
        (item,) = stack.regression.get_run_items(run.run_id)
        assert item["status"] == "cancelled"
        # 已终态的批次不可重复取消（409 语义）
        with pytest.raises(RegressionError) as exc_info:
            await stack.regression.cancel_run(run.run_id)
        assert exc_info.value.code == "REGRESSION_RUN_NOT_RUNNING"


def test_terminal_operation_log_marks_failure(
    stack: AppStack,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """终态推进失败必须输出 error 操作日志，不能误记 success。"""

    def fail_lookup(_task_id: str):
        raise RuntimeError("terminal lookup failed")

    monkeypatch.setattr(stack.regression._storage, "get_regression_item_by_task_id", fail_lookup)
    monkeypatch.setattr(aspect, "_OPERATION_LOGGING_CACHE", True)
    operation_logger = logging.getLogger("argus.operation")
    caplog.set_level(logging.INFO, logger="argus.operation")
    operation_logger.addHandler(caplog.handler)
    try:
        stack.regression.handle_task_terminal("task-broken", "completed")
    finally:
        operation_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "regression.task_terminal"
    ]
    assert records
    assert getattr(records[-1], "status", None) == "error"


class TestQueueFullAbort:
    async def test_abort_marks_failed_and_skips_rest(self, small_queue_stack: AppStack) -> None:
        stack = small_queue_stack
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input("用例一"))
        stack.regression.create_case(pid, _blackbox_input("用例二", displayOrder=1))

        with pytest.raises(RegressionError) as exc_info:
            await stack.regression.create_run(pid)
        assert exc_info.value.code == "TASK_QUEUE_FULL"
        assert exc_info.value.http_status == 503

        # 找到失败批次（项目只有一个）
        runs, total = stack.regression.list_runs(pid)
        assert total == 1
        run = runs[0]
        assert run.status.value == "failed"
        assert run.error_code == "REGRESSION_QUEUE_FULL"

        # 已提交的子任务均未开始执行 → 全部回收为 cancelled
        # （容量 1：用例一入队后被回收；用例二创建后未及入队即中止，同样取消）
        items = sorted(
            stack.regression.get_run_items(run.run_id),
            key=lambda i: i["displayOrder"],
        )
        assert {i["status"] for i in items} == {"cancelled"}
        for item in items:
            task = stack.reader.get_task(item["taskId"])
            assert task.status.value == "cancelled"


class TestRecovery:
    async def test_recover_unfinished_run_cancels_orphans_and_finalizes(
        self, tmp_path: Path
    ) -> None:
        """进程重启后：非终态子任务永远无人执行 → 取消并以门禁失败收尾。"""
        stack = make_app_stack(tmp_path)
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())
        run = await stack.regression.create_run(pid)

        # 模拟重启：丢弃内存队列（新栈的 queue 为空），仅保留 DB 状态
        stale_storage = TaskSQLiteStorage(tmp_path / "argus.db")
        lifecycle = TaskLifecycleService(stale_storage, event_publisher=None)

        recovered_service = RegressionService(
            storage=stale_storage,
            lifecycle=lifecycle,
            queue=TaskQueue(max_size=0),
            resolve_create_params=lambda **kwargs: kwargs,  # 恢复路径不触达
            event_publisher=None,
        )
        finalized = recovered_service.recover_stale_runs()
        assert finalized == 1

        finished = recovered_service.get_run(run.run_id)
        assert finished.gate_result is not None
        assert finished.status.value == "completed"
        assert finished.gate_result.value == "failed"
        summary = json.loads(finished.summary_json)
        # 孤儿子任务被取消 → 批次项 cancelled → 门禁显式失败
        assert summary["itemCounts"]["cancelled"] == 1
        reasons = summary["blockingReasons"]
        assert any("未成功" in r for r in reasons)

    async def test_recover_creation_interrupted_batch_fails_gate(self, tmp_path: Path) -> None:
        """提交阶段崩溃（批次项无 task_id）→ cancelled → 门禁失败而非误通过。"""
        stack = make_app_stack(tmp_path)
        pid = await _make_project(stack)
        case = stack.regression.create_case(pid, _blackbox_input())

        # 手工落库一个"创建中断"的批次：pending + 批次项无 task_id
        from argus_py.core.ids import generate_id
        from argus_py.regression.enums import (
            RegressionItemStatus,
            RegressionRunStatus,
            RegressionTriggerSource,
        )
        from argus_py.regression.models import RegressionRun, RegressionRunItem

        now = "2026-08-26T00:00:00+00:00"
        run = RegressionRun(
            run_id=generate_id("regrun"),
            project_id=pid,
            trigger_source=RegressionTriggerSource.API,
            status=RegressionRunStatus.PENDING,
            created_at=now,
        )
        item = RegressionRunItem(
            item_id=generate_id("regitem"),
            run_id=run.run_id,
            case_id=case.case_id,
            case_name=case.name,
            display_order=0,
            case_snapshot_json="{}",
            status=RegressionItemStatus.PENDING,
            created_at=now,
        )
        stack.reader.storage.create_regression_run_with_items(run, [item])

        assert stack.regression.recover_stale_runs() == 1

        finished = stack.regression.get_run(run.run_id)
        assert finished.status.value == "completed"
        # 关键断言：全中断批次不得误判为 passed
        assert finished.gate_result is not None
        assert finished.gate_result.value == "failed"
        summary = json.loads(finished.summary_json)
        assert summary["itemCounts"]["cancelled"] == 1
        assert summary["blockingReasons"]

    async def test_recover_skips_already_terminal_runs(self, stack: AppStack) -> None:
        pid = await _make_project(stack)
        stack.regression.create_case(pid, _blackbox_input())
        run = await stack.regression.create_run(pid)
        (item,) = stack.regression.get_run_items(run.run_id)
        _finish_task(stack, item["taskId"])

        assert stack.regression.recover_stale_runs() == 0
