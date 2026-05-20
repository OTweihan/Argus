"""冻结审计负载（audit payload）字段结构。

所有 audit() 调用的 **details 字段名必须为 snake_case。
API schema 侧保持 camelCase（与 OpenAPI 一致），但审计日志本身统一命名，
避免告警规则同时维护两套字段名。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.service import ModelConfigService
from argus_py.core.enums import TaskStatus, TaskType
from argus_py.project.service import ProjectService
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.storage import TaskSQLiteStorage


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "argus.db"


@pytest.fixture
def project_service(tmp_db: Path) -> ProjectService:
    return ProjectService(ProjectSQLiteStorage(tmp_db))


@pytest.fixture
def model_service(tmp_db: Path) -> ModelConfigService:
    return ModelConfigService(ModelConfigSQLiteStorage(tmp_db))


@pytest.fixture
def lifecycle_service(tmp_db: Path) -> TaskLifecycleService:
    return TaskLifecycleService(
        TaskSQLiteStorage(tmp_db),
        event_publisher=None,
    )


def _capture_audit_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, tuple, dict[str, Any]]]:
    """捕获所有 audit() 调用，返回列表 [(action, args, kwargs)]。"""
    calls: list[tuple[str, tuple, dict[str, Any]]] = []

    def _fake_audit(action: str, *args: Any, **kwargs: Any) -> None:
        calls.append((action, args, kwargs))

    # auduit 被 observability/__init__.py 重新导出，需要通过引用点 patch
    for mod_path in (
        "argus_py.project.service",
        "argus_py.config.service",
        "argus_py.task.lifecycle",
    ):
        monkeypatch.setattr(f"{mod_path}.audit", _fake_audit)
    return calls


def _assert_snake_case_keys(d: dict[str, Any]) -> None:
    """断言 audit() 顶层 keyword 名为 snake_case。

    不递归嵌套 dict——底层数据 payloads（如 task=）保持 camelCase，
    与 OpenAPI schema 对齐。
    """
    for k in d:
        if not k.startswith("_"):
            assert "_" in k or k.islower() or k.isdigit(), (
                f"audit keyword '{k}' should be snake_case"
            )


# ── ProjectService audit ─────────────────────────────────────────


class TestProjectAuditPayload:
    def test_create_project_fields(self, project_service: ProjectService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        project_service.create_project(name="test-project")
        assert len(calls) == 1
        action, _args, kwargs = calls[0]
        assert action == "project.create"
        assert set(kwargs.keys()) == {"project_id", "name"}

    def test_update_project_fields(self, project_service: ProjectService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        p = project_service.create_project(name="test-project")
        project_service.update_project(p.project_id, {"description": "updated"})
        audit_calls = [c for c in calls if c[0] == "project.update"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"project_id", "fields"}

    def test_delete_project_fields(self, project_service: ProjectService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        p = project_service.create_project(name="test-project")
        project_service.delete_project(p.project_id)
        audit_calls = [c for c in calls if c[0] == "project.delete"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"project_id", "name"}


# ── ModelConfigService audit ──────────────────────────────────────


class TestModelConfigAuditPayload:
    def test_create_fields(self, model_service: ModelConfigService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        model_service.create_model_config(name="test-model", provider="openai", model="gpt-4")
        assert len(calls) == 1
        action, _args, kwargs = calls[0]
        assert action == "model_config.create"
        assert set(kwargs.keys()) == {"model_config_id", "name", "provider", "model"}

    def test_update_fields(self, model_service: ModelConfigService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        mc = model_service.create_model_config(name="test-model", provider="openai", model="gpt-4")
        model_service.update_model_config(mc.model_config_id, {"name": "renamed"})
        audit_calls = [c for c in calls if c[0] == "model_config.update"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"model_config_id", "fields"}

    def test_delete_fields(self, model_service: ModelConfigService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        mc = model_service.create_model_config(name="test-model", provider="openai", model="gpt-4")
        model_service.delete_model_config(mc.model_config_id)
        audit_calls = [c for c in calls if c[0] == "model_config.delete"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"model_config_id"}


# ── TaskLifecycleService audit ────────────────────────────────────


class TestTaskAuditPayload:
    def test_create_fields(self, lifecycle_service: TaskLifecycleService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        lifecycle_service.create_task(goal="test task")
        audit_calls = [c for c in calls if c[0] == "task.create"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"task_id", "task"}

    def test_update_fields(self, lifecycle_service: TaskLifecycleService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        task = lifecycle_service.create_task(goal="test task")
        lifecycle_service.update_task_info(
            task,
            goal="updated goal",
            name="x",
            start_url=None,
            task_type=TaskType.BLACKBOX,
            project_id=None,
            max_steps=10,
            timeout_seconds=60,
            capture_screenshots=True,
            parameters={},
        )
        audit_calls = [c for c in calls if c[0] == "task.update"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"task_id", "task"}

    def test_delete_fields(self, lifecycle_service: TaskLifecycleService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        task = lifecycle_service.create_task(goal="test task")
        lifecycle_service.delete_pending_task(task)
        audit_calls = [c for c in calls if c[0] == "task.delete"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"task_id"}

    def test_restart_fields(self, lifecycle_service: TaskLifecycleService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        task = lifecycle_service.create_task(goal="test task")
        lifecycle_service.update_status(task, TaskStatus.RUNNING)
        lifecycle_service.update_status(task, TaskStatus.FAILED, "error")
        lifecycle_service.restart_task(task)
        audit_calls = [c for c in calls if c[0] == "task.restart"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"task_id", "source_task_id", "task"}

    def test_cancel_fields(self, lifecycle_service: TaskLifecycleService, monkeypatch) -> None:
        calls = _capture_audit_calls(monkeypatch)
        task = lifecycle_service.create_task(goal="test task")
        lifecycle_service.update_status(task, TaskStatus.RUNNING)
        lifecycle_service.cancel_task(task)
        audit_calls = [c for c in calls if c[0] == "task.cancel"]
        assert len(audit_calls) == 1
        _action, _args, kwargs = audit_calls[0]
        assert set(kwargs.keys()) == {"task_id", "status", "previous_status"}


# ── 全局 snake_case 约束 ──────────────────────────────────────────


class TestAuditPayloadSnakeCase:
    """断言所有 audit 调用的 details key 均为 snake_case。"""

    def test_all_payload_keys_are_snake_case(
        self,
        project_service: ProjectService,
        model_service: ModelConfigService,
        lifecycle_service: TaskLifecycleService,
        monkeypatch,
    ) -> None:
        captured: list[dict[str, Any]] = []

        def _fake_audit(action: str, **kwargs: Any) -> None:
            captured.append(kwargs)

        for mod_path in (
            "argus_py.project.service",
            "argus_py.config.service",
            "argus_py.task.lifecycle",
        ):
            monkeypatch.setattr(f"{mod_path}.audit", _fake_audit)

        # 触发所有审计动作
        p = project_service.create_project(name="audit-test")
        model_service.create_model_config(name="audit-model", provider="openai", model="gpt-4o")
        t = lifecycle_service.create_task(goal="audit task")

        project_service.update_project(p.project_id, {"description": "x"})
        lifecycle_service.update_task_info(
            t,
            goal="updated",
            name="x",
            start_url=None,
            task_type=TaskType.BLACKBOX,
            project_id=None,
            max_steps=10,
            timeout_seconds=60,
            capture_screenshots=True,
            parameters={},
        )
        project_service.delete_project(p.project_id)

        # 遍历所有审计调用
        for kwargs in captured:
            _assert_snake_case_keys(kwargs)
