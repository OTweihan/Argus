"""阶段四：Python↔Java 跨语言 Golden 契约测试。

读取 tests/contracts/whitebox/*.json 作为共享契约文件，
验证 Python 侧反序列化 → 再序列化是正确的。
"""

from __future__ import annotations

import json
from pathlib import Path

from argus_py.whitebox.models import WhiteboxJobStatus, WhiteboxResult

_GOLDEN_DIR = Path(__file__).parent.parent / "contracts" / "whitebox"


def _load(name: str) -> dict:
    return json.loads((_GOLDEN_DIR / name).read_text("utf-8"))


# ── Analyze Request ─────────────────────────────────────────────


def test_analyze_request_fields() -> None:
    data = _load("analyze-request.json")
    assert data["sourcePath"] == "/tmp/test-project"
    assert data["scope"] == "all"
    assert data["targetModules"] == ["core", "api"]
    assert data["classpathMode"] == "auto"


# ── Job Status ──────────────────────────────────────────────────


def test_job_status_deserialization() -> None:
    data = _load("analysis-job-status.json")
    status = WhiteboxJobStatus.from_dict(data)
    assert status.job_id == "job-abc123"
    assert status.status == "RUNNING"
    assert status.stage == "analysis"
    assert len(status.events) == 2
    assert status.events[0].event_id == "evt-001"
    assert status.events[0].sequence == 0


# ── Complete Result ─────────────────────────────────────────────


def test_complete_result_deserialization() -> None:
    data = _load("analysis-result-complete.json")
    result = WhiteboxResult.from_dict(data)
    assert len(result.endpoints) == 2
    assert result.endpoints[0].path == "/api/users"
    assert result.endpoints[0].http_method == "GET"
    assert result.endpoints[1].path == "/api/users/{id}"
    assert len(result.call_graph.nodes) == 1
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "EMPTY_CATCH"
    assert result.findings[0].rule_category == "BUG"
    assert result.findings[0].analysis_confidence == "HIGH"
    assert len(result.execution_flows) == 1
    assert len(result.clusters) == 1
    assert result.diagnostics is not None
    assert result.diagnostics.classpath_available is True
    assert result.diagnostics.jar_count == 42


def test_complete_result_roundtrip() -> None:
    """Golden JSON → Python model → JSON 序列化 → 关键字段对齐。"""

    data = _load("analysis-result-complete.json")
    result = WhiteboxResult.from_dict(data)

    # 重新序列化后验证 camelCase 字段还在
    from argus_py.whitebox.runner import _serialize_whitebox_result

    serialized = _serialize_whitebox_result(
        result, len(result.endpoints), len(result.findings), "all"
    )
    diag = serialized.get("diagnostics", {})
    assert diag is not None
    assert diag.get("classpathAvailable") is True
    assert diag.get("totalSourceFiles") == 150


# ── Degraded Result ─────────────────────────────────────────────


def test_degraded_result_deserialization() -> None:
    data = _load("analysis-result-degraded.json")
    result = WhiteboxResult.from_dict(data)
    assert result.diagnostics is not None
    assert result.diagnostics.classpath_available is False
    assert result.diagnostics.classpath_source == "none"
    assert result.diagnostics.jar_count == 0


# ── Validate Source ─────────────────────────────────────────────


def test_validate_source_deserialization() -> None:
    """Java validate-source 响应只包含 exists/readable 布尔字段；
    VisibilityStatus 由客户端根据 HTTP 状态和字段类型推导，不直接从 JSON 解析。"""
    data = _load("validate-source-response.json")
    assert isinstance(data["exists"], bool)
    assert data["exists"] is True
    assert isinstance(data["readable"], bool)
    assert data["readable"] is True


# ── Error ───────────────────────────────────────────────────────


def test_error_response_structure() -> None:
    data = _load("error-response.json")
    assert "error" in data
    assert "errorCode" in data
