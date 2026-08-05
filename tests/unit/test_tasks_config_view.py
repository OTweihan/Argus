"""tasks API 白盒配置视图（_build_whitebox_config_view）单元测试。"""

from __future__ import annotations

import json

from argus_py.api.schemas.tasks import (
    ConfigStatus,
    _build_whitebox_config_view,
)
from argus_py.core.enums import TaskType
from argus_py.task.models import Task


def test_view_uses_source_repo_url_for_edit_value() -> None:
    """编辑级 repoUrl 优先取 task.source_repo_url。"""
    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="分析",
        whitebox_config_json=json.dumps(
            {
                "schema_version": 1,
                "source_type": "git",
                "clone_url": "https://github.com/org/repo.git",
                "source_repo_url": "https://github.com/org/repo.git",
                "ref": "main",
            }
        ),
        source_repo_url="https://github.com/org/repo.git",
    )
    view = _build_whitebox_config_view(task)
    assert view is not None
    assert view["status"] == ConfigStatus.VALID
    assert view["config"]["repoUrl"] == "https://github.com/org/repo.git"
    assert view["config"]["ref"] == "main"


def test_view_falls_back_to_persisted_clone_url() -> None:
    """source_repo_url 未持久化时，编辑级 repoUrl 兜底读取 config_json.clone_url。

    回归 2026-08-04 审计项：to_persisted() 写入的键是 clone_url，
    旧代码读取 repo_url 恒为 None（死分支）。
    """
    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="分析",
        whitebox_config_json=json.dumps(
            {
                "schema_version": 1,
                "source_type": "git",
                "clone_url": "https://github.com/org/repo.git",
                "source_repo_url": None,
                "ref": "main",
            }
        ),
        source_repo_url=None,
    )
    view = _build_whitebox_config_view(task)
    assert view is not None
    assert view["status"] == ConfigStatus.VALID
    assert view["config"]["repoUrl"] == "https://github.com/org/repo.git"
    # repoUrlDisplay 仅在展示级脱敏值存在时填充
    assert view["config"]["repoUrlDisplay"] is None


def test_view_non_whitebox_returns_none() -> None:
    task = Task(task_type=TaskType.BLACKBOX, goal="分析")
    assert _build_whitebox_config_view(task) is None


def test_view_invalid_json_returns_parse_error() -> None:
    task = Task(
        task_type=TaskType.WHITEBOX,
        goal="分析",
        whitebox_config_json="{not-json",
    )
    view = _build_whitebox_config_view(task)
    assert view is not None
    assert view["status"] == ConfigStatus.INVALID
    assert view["errorCode"] == "PARSE_ERROR"
