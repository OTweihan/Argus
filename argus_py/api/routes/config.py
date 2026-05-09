"""配置管理路由。"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, Query, Response, status

from argus_py.api.dependencies import get_model_config_service, load_server_settings
from argus_py.api.schemas import (
    ConfigSummaryResponse,
    ModelConfigCreateRequest,
    ModelConfigListResponse,
    ModelConfigResponse,
    ModelConfigTestRequest,
    ModelConfigUpdateRequest,
    ModelConnectionTestResponse,
)
from argus_py.config.models import ModelConfig
from argus_py.config.service import ModelConfigService
from argus_py.core.exceptions import ModelConfigError
from argus_py.llm.providers import get_provider_spec

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/summary", response_model=ConfigSummaryResponse)
async def get_config_summary() -> ConfigSummaryResponse:
    """返回非敏感配置摘要。"""
    settings = load_server_settings()
    model_service = get_model_config_service()
    model_configs = model_service.list_model_configs()
    default_model_config = model_service.get_default_model_config()
    return ConfigSummaryResponse(
        server_host=settings.host,
        server_port=settings.port,
        cors_allow_origins=settings.cors_allow_origins,
        scheduler_concurrency=settings.scheduler_concurrency,
        scheduler_queue_max_size=settings.scheduler_queue_max_size,
        scheduler_shutdown_timeout_seconds=settings.scheduler_shutdown_timeout_seconds,
        events_history_limit=settings.events_history_limit,
        events_subscriber_queue_size=settings.events_subscriber_queue_size,
        model_configs_count=len(model_configs),
        default_model_config_id=default_model_config.model_config_id if default_model_config else None,
    )


@router.get("/models", response_model=ModelConfigListResponse)
async def list_model_configs(
    include_disabled: bool = Query(default=True, alias="includeDisabled"),
    service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConfigListResponse:
    """列出模型配置。"""
    configs = service.list_model_configs(include_disabled=include_disabled)
    return ModelConfigListResponse(
        total=len(configs),
        models=[ModelConfigResponse.from_model_config(config) for config in configs],
    )


@router.post("/models", response_model=ModelConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_model_config(
    request: ModelConfigCreateRequest,
    service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConfigResponse:
    """创建模型配置。"""
    config = service.create_model_config(
        name=request.name,
        provider=request.provider,
        model=request.model,
        api_key=request.api_key,
        base_url=request.base_url,
        completions_path=request.completions_path,
        max_retries=request.max_retries,
        timeout_seconds=request.timeout_seconds,
        task_type=request.task_type,
        is_default=request.is_default,
        enabled=request.enabled,
    )
    return ModelConfigResponse.from_model_config(config)


@router.post("/models/test", response_model=ModelConnectionTestResponse)
async def test_model_config(
    request: ModelConfigTestRequest,
    service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConnectionTestResponse:
    """测试已保存或临时模型配置。"""
    config = _resolve_test_config(request, service)
    try:
        result = await service.test_model_config(config)
    except Exception as exc:
        raise ModelConfigError(f"模型连接测试失败：{exc}") from exc
    return ModelConnectionTestResponse(**result)


@router.get("/models/{model_config_id}", response_model=ModelConfigResponse)
async def get_model_config(
    model_config_id: str,
    service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConfigResponse:
    """查询模型配置详情。"""
    return ModelConfigResponse.from_model_config(service.get_model_config(model_config_id))


@router.put("/models/{model_config_id}", response_model=ModelConfigResponse)
async def update_model_config(
    model_config_id: str,
    request: ModelConfigUpdateRequest,
    service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConfigResponse:
    """更新模型配置。"""
    updates = request.model_dump(exclude_unset=True)
    return ModelConfigResponse.from_model_config(service.update_model_config(model_config_id, updates))


@router.delete("/models/{model_config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_config(
    model_config_id: str,
    service: ModelConfigService = Depends(get_model_config_service),
) -> Response:
    """删除模型配置。"""
    service.delete_model_config(model_config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _resolve_test_config(
    request: ModelConfigTestRequest,
    service: ModelConfigService,
) -> ModelConfig:
    """解析连接检查使用的模型配置，不持久化临时配置。"""
    if request.model_config_id:
        config = service.get_model_config(request.model_config_id)
        updates = {
            key: value
            for key, value in request.model_dump(exclude_unset=True).items()
            if key != "model_config_id" and value is not None
        }
        return replace(config, **_normalize_test_updates(config, updates))

    provider = request.provider or ""
    model = (request.model or "").strip()
    if not model:
        raise ModelConfigError("连接检查需要提供 model，或传入已保存的 modelConfigId。")
    spec = get_provider_spec(provider)
    return ModelConfig(
        name="connection-test",
        provider=provider,
        model=model,
        api_key=(request.api_key or "").strip(),
        base_url=(request.base_url or spec.default_base_url).strip().rstrip("/"),
        completions_path=request.completions_path or spec.completions_path,
        max_retries=request.max_retries if request.max_retries is not None else 0,
        timeout_seconds=request.timeout_seconds or 30.0,
    )


def _normalize_test_updates(
    config: ModelConfig,
    updates: dict[str, object],
) -> dict[str, object]:
    """规范化连接检查覆盖项。"""
    normalized = dict(updates)
    provider = normalized.get("provider")
    if "base_url" not in normalized:
        normalized["base_url"] = get_provider_spec(provider).default_base_url
    if "base_url" in normalized and normalized["base_url"] is not None:
        normalized["base_url"] = str(normalized["base_url"]).strip().rstrip("/")
    if "completions_path" in normalized:
        path = str(normalized["completions_path"] or config.completions_path).strip()
        normalized["completions_path"] = path if path.startswith("/") else f"/{path}"
    if "api_key" in normalized and normalized["api_key"] is not None:
        normalized["api_key"] = str(normalized["api_key"]).strip()
    return normalized
