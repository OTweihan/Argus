"""后端可观测性基础设施。"""

from argus_py.observability.aspect import log_operation
from argus_py.observability.audit import AuditService, audit
from argus_py.observability.context import bind_context, current_context
from argus_py.observability.events import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_SUCCESS,
    log_event,
)
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
    "STATUS_CANCELLED",
    "STATUS_ERROR",
    "STATUS_SUCCESS",
    "audit",
    "bind_context",
    "current_context",
    "log_event",
    "log_operation",
    "write_trace",
]
