"""测试工厂 — 提供 make_* 函数以创建合法默认实体。

使用方式::

    from tests.factories.requests import make_http_request_evidence
    from tests.factories.analysis import make_endpoint_dict
    from tests.factories.correlation import make_correlation_run

每个工厂生成合法实体，测试仅覆盖变化的字段。
"""

from tests.factories.analysis import make_analysis_run, make_endpoint_dict
from tests.factories.correlation import (
    make_correlation_attempt,
    make_correlation_run,
    make_endpoint_evidence,
    make_endpoint_evidence_candidate,
)
from tests.factories.requests import make_capture_quality, make_http_request_evidence

__all__ = [
    "make_analysis_run",
    "make_capture_quality",
    "make_correlation_attempt",
    "make_correlation_run",
    "make_endpoint_dict",
    "make_endpoint_evidence",
    "make_endpoint_evidence_candidate",
    "make_http_request_evidence",
]
