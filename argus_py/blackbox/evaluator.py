"""黑盒执行结果评估器。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from argus_py.blackbox.prompts import load_evaluator_prompt
from argus_py.config.llm_settings import load_llm_settings
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
        completed_flag = _parse_bool(data.get("completed"))
        next_action_raw = "" if completed_flag else str(data.get("next_action") or "").strip()
        return cls(
            completed=completed_flag,
            success=_parse_bool(data.get("success")),
            reason=str(data.get("reason") or ""),
            next_action=next_action_raw,
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
        sys_prompt = load_evaluator_prompt()
        payload = {
            "goal": goal,
            "observation": observation,
            "history": history or [],
        }
        prompt = "\n\n输入：\n" + json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)

        trace_ctx: dict[str, Any] = {
            "trace_id": generate_id("trc"),
            "phase": "evaluator",
            "system_prompt": sys_prompt,
            "input_payload": payload,
        }

        write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_STARTED))

        try:
            response = await self._client().complete(
                prompt=prompt,
                system_prompt=sys_prompt,
                response_format={"type": "json_object"},
                _trace_ctx=trace_ctx,
            )
        except Exception as exc:
            trace_ctx.setdefault("error", str(exc))
            write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_FAILED))
            raise

        trace_ctx["raw_response"] = response.content

        try:
            data = extract_json(response.content)
            validate_required_keys(data, ["completed", "success", "reason"])
            trace_ctx["parsed_result"] = data
            write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_SUCCEEDED))
            return EvaluationResult.from_dict(data)
        except Exception as exc:
            trace_ctx["parse_error"] = str(exc)
            write_trace(LLMTraceRecord.from_trace_ctx(trace_ctx, EVENT_LLM_PARSE_FAILED))
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
