"""验证 LLMBoundaryFactory 从 project / task parameters 提取 prompt 扩展。"""

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from argus_py.blackbox.evaluator import BlackboxEvaluator
from argus_py.blackbox.llm_boundary import LLMBoundaryFactory
from argus_py.blackbox.planner import BlackboxPlanner
from argus_py.core.exceptions import ProjectNotFoundError
from argus_py.project.models import Project
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.models import Task


class _FakeStorage:
    """假 ProjectSQLiteStorage：构造时塞入项目字典，按 ID 直读。

    与生产语义一致：项目缺失抛 ``ProjectNotFoundError``；可通过 ``raise_on_load``
    模拟"DB 不可用 / 加密 key 缺失"等真实环境异常。
    """

    def __init__(
        self,
        projects: dict[str, Project],
        *,
        raise_on_load: Exception | None = None,
    ) -> None:
        self._projects = projects
        self._raise_on_load = raise_on_load

    def load(self, project_id: str) -> Project:
        if self._raise_on_load is not None:
            raise self._raise_on_load
        if project_id not in self._projects:
            raise ProjectNotFoundError(f"Project not found: {project_id}")
        return self._projects[project_id]


def _fake_storage(
    projects: dict[str, Project] | None = None,
    *,
    raise_on_load: Exception | None = None,
) -> ProjectSQLiteStorage:
    """把 _FakeStorage 实例伪装成 ProjectSQLiteStorage，喂给 LLMBoundaryFactory。

    LLMBoundaryFactory 只会调用 ``storage.load(project_id)``，鸭子类型即可；
    用 cast 把测试桩当成正式类型，避免 mypy 抱怨。
    """
    return cast(
        ProjectSQLiteStorage,
        _FakeStorage(projects or {}, raise_on_load=raise_on_load),
    )


@pytest.fixture
def fake_llm_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """替换 resolve_llm_client_for_task，避免真实读取 LLM 配置。"""
    client = MagicMock()
    monkeypatch.setattr(
        "argus_py.blackbox.llm_boundary.resolve_llm_client_for_task",
        lambda task: client,
    )
    return client


def _make_task(project_id: str | None = None, **parameters: Any) -> Task:
    return Task(
        goal="test", start_url="http://example.com", project_id=project_id, parameters=parameters
    )


def test_resolve_without_project_or_task_extensions_uses_no_extensions(
    fake_llm_client: MagicMock,
):
    factory = LLMBoundaryFactory(project_storage=_fake_storage())
    task = _make_task()

    planner, evaluator = factory.resolve(task)

    assert isinstance(planner, BlackboxPlanner)
    assert isinstance(evaluator, BlackboxEvaluator)
    assert planner._extensions == []
    assert evaluator._extensions == []


def test_resolve_uses_task_extensions_only(fake_llm_client: MagicMock):
    factory = LLMBoundaryFactory(project_storage=_fake_storage())
    task = _make_task(prompt_extensions={"planner": "TASK_PLAN", "evaluator": "TASK_EVAL"})

    planner, evaluator = factory.resolve(task)

    assert planner._extensions == ["TASK_PLAN"]
    assert evaluator._extensions == ["TASK_EVAL"]


def test_resolve_concatenates_project_then_task_extensions(fake_llm_client: MagicMock):
    project = Project(
        name="demo",
        project_id="prj-1",
        parameters={"prompt_extensions": {"planner": "PROJ_PLAN", "evaluator": "PROJ_EVAL"}},
    )
    factory = LLMBoundaryFactory(project_storage=_fake_storage({"prj-1": project}))
    task = _make_task(
        project_id="prj-1",
        prompt_extensions={"planner": "TASK_PLAN", "evaluator": "TASK_EVAL"},
    )

    planner, evaluator = factory.resolve(task)

    assert planner._extensions == ["PROJ_PLAN", "TASK_PLAN"]
    assert evaluator._extensions == ["PROJ_EVAL", "TASK_EVAL"]


def test_resolve_skips_empty_extensions(fake_llm_client: MagicMock):
    project = Project(
        name="demo",
        project_id="prj-2",
        parameters={"prompt_extensions": {"planner": "", "evaluator": "PROJ_EVAL"}},
    )
    factory = LLMBoundaryFactory(project_storage=_fake_storage({"prj-2": project}))
    task = _make_task(
        project_id="prj-2",
        prompt_extensions={"planner": "TASK_PLAN"},
    )

    planner, evaluator = factory.resolve(task)

    assert planner._extensions == ["TASK_PLAN"]
    assert evaluator._extensions == ["PROJ_EVAL"]


def test_resolve_with_missing_project_falls_back_silently(
    fake_llm_client: MagicMock, caplog: pytest.LogCaptureFixture
):
    """P1-9：项目不存在视为"未配置扩展"语义，仅 debug，不应产生 warning。"""
    caplog.set_level(logging.DEBUG, logger="argus_py.blackbox.llm_boundary")

    factory = LLMBoundaryFactory(project_storage=_fake_storage())
    task = _make_task(
        project_id="prj-not-exist",
        prompt_extensions={"planner": "TASK_PLAN"},
    )

    planner, _ = factory.resolve(task)

    assert planner._extensions == ["TASK_PLAN"]
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []


def test_resolve_with_storage_failure_emits_log_event(
    fake_llm_client: MagicMock, caplog: pytest.LogCaptureFixture
):
    """P1-9：DB / 加密 key 等真实异常应升 warning + 结构化事件。"""
    caplog.set_level(logging.WARNING, logger="argus_py.blackbox.llm_boundary")

    factory = LLMBoundaryFactory(
        project_storage=_fake_storage(raise_on_load=RuntimeError("decrypt failed"))
    )
    task = _make_task(
        project_id="prj-broken",
        prompt_extensions={"planner": "TASK_PLAN"},
    )

    planner, _ = factory.resolve(task)

    # 行为：任务扩展仍生效，项目侧降级为空
    assert planner._extensions == ["TASK_PLAN"]
    # 可观测性：必须出现 warning + 结构化字段
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    record = warnings[0]
    assert getattr(record, "event", None) == "prompt_extension.load"
    assert getattr(record, "status", None) == "error"
    details = getattr(record, "details", {})
    assert details.get("projectId") == "prj-broken"
    assert details.get("errorType") == "RuntimeError"


def test_resolve_with_storage_failure_does_not_break_task_execution(
    fake_llm_client: MagicMock,
):
    """P1-9：即便 storage 抛任意异常，resolve 也不应让任务执行链中断。"""
    factory = LLMBoundaryFactory(
        project_storage=_fake_storage(raise_on_load=ValueError("bad data"))
    )
    task = _make_task(project_id="prj-broken")

    planner, evaluator = factory.resolve(task)

    assert isinstance(planner, BlackboxPlanner)
    assert isinstance(evaluator, BlackboxEvaluator)
    assert planner._extensions == []
    assert evaluator._extensions == []


def test_resolve_ignores_extensions_when_default_planner_injected(
    fake_llm_client: MagicMock,
):
    injected_planner = BlackboxPlanner(prompt_extensions=["EXISTING"])
    injected_evaluator = BlackboxEvaluator(prompt_extensions=["EXISTING_EVAL"])
    factory = LLMBoundaryFactory(
        default_planner=injected_planner,
        default_evaluator=injected_evaluator,
        project_storage=_fake_storage(),
    )
    task = _make_task(prompt_extensions={"planner": "TASK_PLAN"})

    planner, evaluator = factory.resolve(task)

    assert planner is injected_planner
    assert evaluator is injected_evaluator
    assert planner._extensions == ["EXISTING"]
    assert evaluator._extensions == ["EXISTING_EVAL"]
