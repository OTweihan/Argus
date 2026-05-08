"""黑盒任务规划器。"""

from __future__ import annotations

import json
from typing import Any

from argus_py.blackbox.models import ActionSequence, ActionStep, BlackboxTaskInput
from argus_py.blackbox.prompts import load_planner_prompt
from argus_py.config.llm_settings import load_llm_settings
from argus_py.core.enums import ActionType
from argus_py.core.exceptions import LLMError
from argus_py.llm import LLMClient, extract_json, validate_required_keys
from argus_py.utils.jsonx import to_jsonable


class BlackboxPlanner:
    """黑盒动作规划边界。"""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    async def plan_initial(self, task_input: BlackboxTaskInput) -> ActionSequence:
        """生成初始动作序列，先确定性打开起始 URL。"""
        steps = [ActionStep(action=ActionType.GOTO, url=task_input.start_url, reason="打开起始 URL")]
        return ActionSequence(steps=steps, summary="打开起始页面。")

    async def plan_next(
        self,
        goal: str,
        current_url: str,
        page_snapshot: str,
        history: list[dict[str, Any]],
        max_steps: int = 3,
        last_error: dict[str, Any] | None = None,
    ) -> ActionSequence:
        """基于最新页面观察和上一轮失败信息生成下一批动作。"""
        payload = {
            "goal": goal,
            "current_url": current_url,
            "page_snapshot": page_snapshot,
            "history": history,
            "max_steps": max_steps,
        }
        if last_error:
            payload["last_error"] = last_error
        prompt = "\n\n输入：\n" + json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)
        response = await self._client().complete(
            prompt=prompt,
            system_prompt=load_planner_prompt(),
            response_format={"type": "json_object"},
        )

        try:
            data = extract_json(response.content)
            validate_required_keys(data, ["summary", "steps"])
            return ActionSequence.from_dict(data)
        except Exception as exc:
            raise LLMError(f"黑盒规划器响应解析失败：{exc}") from exc

    def _client(self) -> LLMClient:
        """懒加载 LLM 客户端，避免导入或构造时读取敏感配置。"""
        if self.llm_client is None:
            settings = load_llm_settings()
            self.llm_client = LLMClient(
                api_key=settings.api_key,
                base_url=settings.base_url,
                model=settings.model,
                max_tokens=settings.max_tokens,
                temperature=settings.temperature,
                max_retries=settings.max_retries,
            )
        return self.llm_client
