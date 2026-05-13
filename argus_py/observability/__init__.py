"""后端可观测性基础设施。"""

from argus_py.observability.aspect import log_operation
from argus_py.observability.audit import AuditService
from argus_py.observability.context import bind_context, current_context
from argus_py.observability.llm_trace import (
    EVENT_LLM_FAILED,
    EVENT_LLM_PARSE_FAILED,
    EVENT_LLM_STARTED,
    EVENT_LLM_SUCCEEDED,
    LLMTraceRecord,
    write_trace,
)

__all__ = [
    "AuditService",
    "EVENT_LLM_FAILED",
    "EVENT_LLM_PARSE_FAILED",
    "EVENT_LLM_STARTED",
    "EVENT_LLM_SUCCEEDED",
    "LLMTraceRecord",
    "bind_context",
    "current_context",
    "log_operation",
    "write_trace",
]
