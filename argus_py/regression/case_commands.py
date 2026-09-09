"""回归用例 CRUD 与输入校验（可维护性 M3）。

由 ``RegressionService`` 经 Mixin 组合；公开方法名与行为不变。
内部实现模块——请勿单独实例化。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from argus_py.core.constants import utc_now_iso
from argus_py.core.enums import TaskType
from argus_py.core.exceptions import ArgusError
from argus_py.core.ids import generate_id
from argus_py.regression._common import RegressionError
from argus_py.regression.models import CaseSnapshot, RegressionCase

if TYPE_CHECKING:
    from argus_py.task.storage import TaskSQLiteStorage


class CaseCommandsMixin:
    """用例 CRUD + ``_validate_case_input``。

    仅组合进 ``RegressionService``；依赖面见 ``_deps.RegressionServiceDeps``。
    """

    # 本 Mixin 实际使用的注入依赖（mypy 属性面；运行时由门面 __init__ 赋值）
    _storage: TaskSQLiteStorage
    _resolve_create_params: Callable[..., dict[str, Any]]

    def create_case(self, project_id: str, input: dict[str, Any]) -> RegressionCase:
        """创建回归用例；输入经任务创建同一套校验后存储解析结果。"""
        snapshot = self._validate_case_input(project_id, input)
        now = utc_now_iso()
        case = RegressionCase(
            case_id=generate_id("regcase"),
            project_id=project_id,
            name=snapshot.name,
            task_type=snapshot.task_type,
            goal=snapshot.goal,
            start_url=snapshot.start_url,
            max_steps=snapshot.max_steps,
            timeout_seconds=snapshot.timeout_seconds,
            capture_screenshots=snapshot.capture_screenshots,
            parameters_json=json.dumps(snapshot.parameters, ensure_ascii=False),
            whitebox_config_json=snapshot.whitebox_config_json,
            enabled=bool(input.get("enabled", True)),
            display_order=int(input.get("displayOrder", 0) or 0),
            created_at=now,
            updated_at=now,
        )
        return self._storage.create_regression_case(case)

    def update_case(self, case_id: str, updates: dict[str, Any]) -> RegressionCase:
        """更新用例：合并现有配置后整体重新校验，保证存量始终可执行。"""
        case = self._require_case(case_id)
        merged: dict[str, Any] = {
            "taskType": case.task_type.value,
            "goal": case.goal,
            "startUrl": case.start_url,
            "parameters": case.resolved_parameters(),
            "enabled": case.enabled,
            "displayOrder": case.display_order,
        }
        for key in ("name", "goal", "startUrl", "enabled", "displayOrder"):
            if key in updates:
                merged[key] = updates[key]
        if "maxSteps" in updates:
            merged["maxSteps"] = updates["maxSteps"]
        if "timeoutSeconds" in updates:
            merged["timeoutSeconds"] = updates["timeoutSeconds"]
        if "captureScreenshots" in updates and updates["captureScreenshots"] is not None:
            merged["captureScreenshots"] = updates["captureScreenshots"]
        if "parameters" in updates and updates["parameters"] is not None:
            merged["parameters"] = updates["parameters"]
        # taskType 不允许变更：黑盒/白盒输入结构差异过大，改建新用例
        snapshot = self._validate_case_input(
            case.project_id,
            {**merged, "taskType": case.task_type.value},
            fallback_limits=(case.max_steps, case.timeout_seconds, case.capture_screenshots),
        )
        fields: dict[str, Any] = {
            "name": snapshot.name,
            "goal": snapshot.goal,
            "start_url": snapshot.start_url,
            "max_steps": snapshot.max_steps,
            "timeout_seconds": snapshot.timeout_seconds,
            "capture_screenshots": int(snapshot.capture_screenshots),
            "parameters_json": json.dumps(snapshot.parameters, ensure_ascii=False),
            "whitebox_config_json": snapshot.whitebox_config_json,
            "enabled": int(bool(merged.get("enabled", True))),
            "display_order": int(merged.get("displayOrder", 0) or 0),
            "updated_at": utc_now_iso(),
        }
        self._storage.update_regression_case(case_id, fields)
        updated = self._require_case(case_id)
        return updated

    def delete_case(self, case_id: str) -> None:
        """删除用例。历史批次使用快照，不受影响。"""
        self._require_case(case_id)
        self._storage.delete_regression_case(case_id)

    def get_case(self, case_id: str) -> RegressionCase:
        return self._require_case(case_id)

    def list_cases(self, project_id: str, *, enabled_only: bool = False) -> list[RegressionCase]:
        return self._storage.list_regression_cases(project_id, enabled_only=enabled_only)

    def _require_case(self, case_id: str) -> RegressionCase:
        case = self._storage.get_regression_case(case_id)
        if case is None:
            raise RegressionError(
                "REGRESSION_CASE_NOT_FOUND",
                f"回归用例不存在：{case_id}",
                http_status=404,
                details={"caseId": case_id},
            )
        return case

    def _validate_case_input(
        self,
        project_id: str,
        input: dict[str, Any],
        fallback_limits: tuple[int, int, bool] | None = None,
    ) -> CaseSnapshot:
        """校验用例输入并返回解析后的可执行快照。

        复用 ``resolve_create_params``：URL 校验、项目默认值合并、模型配置
        存在性校验、白盒配置 schema 校验与执行限制推断一次完成。
        """
        task_type_raw = input.get("taskType") or TaskType.BLACKBOX.value
        try:
            task_type = TaskType(task_type_raw)
        except ValueError as exc:
            raise RegressionError(
                "REGRESSION_INVALID_INPUT",
                f"不支持的任务类型：{task_type_raw}",
                details={"field": "taskType"},
            ) from exc

        goal = str(input.get("goal") or "").strip()
        if not goal:
            raise RegressionError(
                "REGRESSION_INVALID_INPUT",
                "回归用例需要测试目标（goal）。",
                details={"field": "goal"},
            )

        fb_max_steps, fb_timeout, fb_capture = fallback_limits or (None, None, None)
        try:
            resolved = self._resolve_create_params(
                goal=goal,
                name=str(input.get("name") or "").strip() or None,
                start_url=input.get("startUrl") or None,
                task_type=task_type,
                project_id=project_id or None,
                max_steps=input.get("maxSteps")
                if input.get("maxSteps") is not None
                else fb_max_steps,
                timeout_seconds=(
                    input.get("timeoutSeconds")
                    if input.get("timeoutSeconds") is not None
                    else fb_timeout
                ),
                capture_screenshots=(
                    input.get("captureScreenshots")
                    if input.get("captureScreenshots") is not None
                    else fb_capture
                ),
                parameters=input.get("parameters") or {},
            )
        except ArgusError:
            raise
        except Exception as exc:
            raise RegressionError(
                "REGRESSION_INVALID_INPUT",
                f"用例配置校验失败：{exc}",
                details={"projectId": project_id},
            ) from exc

        name = str(input.get("name") or "").strip()
        if not name:
            name = goal[:40]
        raw_capture = resolved.get("capture_screenshots")
        return CaseSnapshot(
            case_id="",
            name=name,
            task_type=task_type,
            goal=resolved["goal"],
            start_url=resolved.get("start_url"),
            max_steps=int(resolved["max_steps"]),
            timeout_seconds=int(resolved["timeout_seconds"]),
            capture_screenshots=True if raw_capture is None else bool(raw_capture),
            parameters=dict(resolved.get("parameters") or {}),
            whitebox_config_json=resolved.get("whitebox_config_json"),
        )
