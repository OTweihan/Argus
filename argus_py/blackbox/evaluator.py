"""黑盒执行结果评估器。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from argus_py.blackbox.prompts import load_evaluator_prompt
from argus_py.config.llm_settings import load_llm_settings
from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.core.exceptions import LLMError
from argus_py.llm import LLMClient, extract_json, validate_required_keys
from argus_py.task.models import Finding
from argus_py.utils.jsonx import to_jsonable


def _parse_bool(value: Any) -> bool:
    """解析 LLM 返回的布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


@dataclass
class EvaluationResult:
    """评估结果。"""

    completed: bool
    success: bool
    reason: str = ""
    findings: list[Finding] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationResult":
        """从 LLM JSON 对象还原评估结果。"""
        findings: list[Finding] = []
        for item in data.get("findings", []) or []:
            findings.append(
                Finding(
                    title=str(item.get("title") or "未命名问题"),
                    description=str(item.get("description") or ""),
                    severity=FindingSeverity(
                        str(item.get("severity") or FindingSeverity.INFO.value)
                    ),
                    finding_type=FindingType(str(item.get("type") or FindingType.FUNCTIONAL.value)),
                    url=item.get("url"),
                    location=item.get("location"),
                    screenshot_path=item.get("screenshot_path"),
                )
            )
        return cls(
            completed=_parse_bool(data.get("completed")),
            success=_parse_bool(data.get("success")),
            reason=str(data.get("reason") or ""),
            findings=findings,
        )


class BlackboxEvaluator:
    """判断目标是否完成的边界。"""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    async def evaluate(
        self,
        goal: str,
        observation: str,
        history: list[dict[str, Any]] | None = None,
    ) -> EvaluationResult:
        """调用 LLM 判断目标是否完成。"""
        payload = {
            "goal": goal,
            "observation": observation,
            "history": history or [],
        }
        prompt = "\n\n输入：\n" + json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)
        response = await self._client().complete(
            prompt=prompt,
            system_prompt=load_evaluator_prompt(),
            response_format={"type": "json_object"},
        )

        try:
            data = extract_json(response.content)
            validate_required_keys(data, ["completed", "success", "reason"])
            return EvaluationResult.from_dict(data)
        except Exception as exc:
            raise LLMError(f"黑盒评估器响应解析失败：{exc}") from exc

    def _client(self) -> LLMClient:
        """懒加载 LLM 客户端。"""
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
