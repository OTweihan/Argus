"""项目管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from argus_py.api.dependencies import get_project_service
from argus_py.api.schemas import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from argus_py.project.service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    service: ProjectService = Depends(get_project_service),
) -> ProjectListResponse:
    """列出项目。"""
    projects = service.list_projects()
    return ProjectListResponse(
        total=len(projects),
        projects=[ProjectResponse.from_project(project) for project in projects],
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """创建项目。"""
    project = service.create_project(
        name=request.name,
        description=request.description,
        base_url=request.base_url,
        git_url=request.git_url,
        auth_state_name=request.auth_state_name,
        default_max_steps=request.default_max_steps,
        default_timeout_seconds=request.default_timeout_seconds,
        default_capture_screenshots=request.default_capture_screenshots,
        parameters=request.parameters,
    )
    return ProjectResponse.from_project(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """查询项目详情。"""
    return ProjectResponse.from_project(service.get_project(project_id))


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """更新项目。"""
    updates = request.model_dump(exclude_unset=True)
    return ProjectResponse.from_project(service.update_project(project_id, updates))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> Response:
    """删除项目。"""
    service.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
