"""黑盒执行结果评估器。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from argus_py.blackbox._client import create_default_client
from argus_py.blackbox.prompts import compose_evaluator_prompt
from argus_py.core.enums import FindingSeverity, FindingType
from argus_py.core.exceptions import LLMError
from argus_py.core.ids import generate_id
from argus_py.llm import LLMClient, extract_json, validate_required_keys
from argus_py.observability.llm_trace import (
    EVENT_LLM_FAILED,
    EVENT_LLM_PARSE_FAILED,
    EVENT_LLM_STARTED,
    EVENT_LLM_SUCCEEDED,
    LLMTraceRecord,
    write_trace,
)
from argus_py.task.models import Finding
from argus_py.utils.jsonx import to_jsonable
from argus_py.utils.parse import parse_bool


@dataclass
class EvaluationResult:
    """评估结果。"""

    completed: bool
    success: bool
    reason: str = ""
    next_action: str = ""
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
        # completed=true 时 next_action 必须为空，避免下一轮把已完成任务又当作新提示
        completed_flag = parse_bool(data.get("completed"))
        next_action_raw = "" if completed_flag else str(data.get("next_action") or "").strip()
        return cls(
            completed=completed_flag,
            success=parse_bool(data.get("success")),
            reason=str(data.get("reason") or ""),
            next_action=next_action_raw,
            findings=findings,
        )


class BlackboxEvaluator:
    """判断目标是否完成的边界。"""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        prompt_extensions: list[str] | None = None,
        task_parameters: dict[str, str] | None = None,
    ) -> None:
        self.llm_client = llm_client
        self._extensions: list[str] = list(prompt_extensions or [])
        self._task_parameters: dict[str, str] = dict(task_parameters or {})

    async def evaluate(
        self,
        goal: str,
        observation: str,
        history: list[dict[str, Any]] | None = None,
    ) -> EvaluationResult:
        """调用 LLM 判断目标是否完成。"""
        sys_prompt = compose_evaluator_prompt(*self._extensions)
        payload: dict[str, Any] = {
            "goal": goal,
            "observation": observation,
            "history": history or [],
        }
        if self._task_parameters:
            payload["task_parameters"] = self._task_parameters
        prompt = "\n\n输入：\n" + json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)

        trace_ctx: dict[str, Any] = {
            "trace_id": generate_id("trc"),
            "phase": "evaluator",
            "system_prompt": sys_prompt,
            "input_payload": payload,
        }

        await write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_STARTED))

        try:
            response = await self._client().complete(
                prompt=prompt,
                system_prompt=sys_prompt,
                response_format={"type": "json_object"},
                _trace_ctx=trace_ctx,
            )
        except LLMError as exc:
            trace_ctx.setdefault("error", str(exc))
            await write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_FAILED))
            raise

        trace_ctx["raw_response"] = response.content

        try:
            data = extract_json(response.content)
            validate_required_keys(data, ["completed", "success", "reason"])
            trace_ctx["parsed_result"] = data
            await write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_SUCCEEDED))
            return EvaluationResult.from_dict(data)
        except (ValueError, KeyError, TypeError) as exc:
            trace_ctx["parse_error"] = str(exc)
            await write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_PARSE_FAILED))
            raise LLMError(f"黑盒评估器响应解析失败：{exc}") from exc

    def _client(self) -> LLMClient:
        """懒加载 LLM 客户端。"""
        if self.llm_client is None:
            self.llm_client = create_default_client()
        return self.llm_client
