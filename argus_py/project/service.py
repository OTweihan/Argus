"""项目管理服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from argus_py.core.exceptions import ProjectError
from argus_py.project.models import Project
from argus_py.project.storage import ProjectSQLiteStorage
from argus_py.task.service import TaskService


class ProjectService:
    """项目 CRUD 业务逻辑。"""

    def __init__(
        self,
        storage: ProjectSQLiteStorage | None = None,
        task_service: TaskService | None = None,
    ) -> None:
        self.storage = storage or ProjectSQLiteStorage()
        self.task_service = task_service or TaskService()

    def create_project(
        self,
        name: str,
        description: str | None = None,
        base_url: str | None = None,
        git_url: str | None = None,
        auth_state_name: str | None = None,
        default_max_steps: int | None = None,
        default_timeout_seconds: int | None = None,
        default_capture_screenshots: bool = True,
        parameters: dict[str, Any] | None = None,
    ) -> Project:
        """创建项目。"""
        resolved_name = name.strip()
        if not resolved_name:
            raise ProjectError("项目名称不能为空。")

        project = Project(
            name=resolved_name,
            description=_normalize_optional_text(description),
            base_url=_normalize_optional_text(base_url),
            git_url=_normalize_optional_text(git_url),
            auth_state_name=_normalize_optional_text(auth_state_name),
            default_max_steps=default_max_steps,
            default_timeout_seconds=default_timeout_seconds,
            default_capture_screenshots=default_capture_screenshots,
            parameters=parameters or {},
        )
        return self.storage.save(project)

    def get_project(self, project_id: str) -> Project:
        """查询项目。"""
        return self.storage.load(project_id)

    def list_projects(self) -> list[Project]:
        """列出项目。"""
        return self.storage.list_projects()

    def update_project(self, project_id: str, updates: dict[str, Any]) -> Project:
        """局部更新项目。"""
        project = self.get_project(project_id)
        for field_name, value in updates.items():
            if field_name == "parameters" and value is None:
                value = {}
            if field_name == "default_capture_screenshots" and value is None:
                continue
            if field_name == "name":
                value = str(value).strip()
                if not value:
                    raise ProjectError("项目名称不能为空。")
            if field_name in {
                "description",
                "base_url",
                "git_url",
                "auth_state_name",
            }:
                value = _normalize_optional_text(value)
            if not hasattr(project, field_name):
                raise ProjectError(f"不支持更新的项目字段：{field_name}")
            setattr(project, field_name, value)
        project.updated_at = datetime.now(timezone.utc)
        return self.storage.save(project)

    def delete_project(self, project_id: str) -> None:
        """删除项目；存在关联任务时不允许删除。"""
        project = self.get_project(project_id)
        tasks = self.task_service.list_tasks(project_id=project.project_id)
        if tasks:
            raise ProjectError(f"项目已关联 {len(tasks)} 个任务，不能删除。")
        self.storage.delete(project.project_id)

    def exists(self, project_id: str) -> bool:
        """判断项目是否存在。"""
        return self.storage.exists(project_id)


def _normalize_optional_text(value: str | None) -> str | None:
    """把空字符串统一归一为 None。"""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None
