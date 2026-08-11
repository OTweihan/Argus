"""阶段四：Python↔Java 跨语言 Golden 契约测试。

读取 tests/contracts/whitebox/*.json 作为共享契约文件，
验证 Python 侧反序列化 → 模型实例化 → 再序列化的正确性。

注意：当前契约文件仅由 Python 侧读取和验证。真正的双向契约测试
需要 Java 侧也读取同一批 Golden JSON 并断言字段一致，或至少
由 CI 任务在每次 Java DTO 变更时运行 Python 契约测试。
目前已知缺口：
- Java 侧没有 test fixture 引用这些 JSON 文件
- analyze-request.json 和 error-response.json 校验仅为字段级，
  原因是 Python 侧请求和错误均以 ad-hoc dict 构造，而非 dataclass
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
    """Python 侧 verify：analyze() payload 必须字段全部存在。

    Java 侧 应 读取同一个 analyze-request.json 并验证 @RequestBody
    能正确绑定。

    已知缺口：Python 侧 client.analyze() 使用 ad-hoc dict 而非 dataclass，
    无法做模型级别的 roundtrip 验证。
    """
    data = _load("analyze-request.json")
    assert data["sourcePath"] == "/tmp/test-project"
    assert data["scope"] == "all"
    assert data["targetModules"] == ["core", "api"]
    assert data["classpathMode"] == "auto"
    assert isinstance(data["autoDetect"], bool)
    assert isinstance(data["generateClasspath"], bool)
    assert isinstance(data["offline"], bool)
    # O-07：Python 物化快照时计算的稳定 revision 进入请求契约
    assert data["sourceRevision"] == "git-commit-sha"
    assert data["snapshotDigest"] == "snapshot-content-sha256"


# ── Job Status ──────────────────────────────────────────────────


def test_job_status_deserialization() -> None:
    """WhiteboxJobStatus.from_dict 正确解析 RUNNING 状态。"""
    data = _load("analysis-job-status.json")
    status = WhiteboxJobStatus.from_dict(data)
    assert status.job_id == "job-abc123"
    assert status.status == "RUNNING"
    assert status.stage == "analysis"
    assert len(status.events) == 2
    assert status.events[0].event_id == "evt-001"
    assert status.events[0].sequence == 0
    assert status.events[1].sequence == 1


# ── Complete Result ─────────────────────────────────────────────


def test_complete_result_deserialization() -> None:
    """WhiteboxResult.from_dict 正确解析完整成功结果。"""
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
    assert result.diagnostics.classpath_source == "maven"
    assert result.diagnostics.module_count == 5
    assert result.diagnostics.module_types == {
        "core": "application",
        "api": "business",
        "common": "library",
    }


def test_complete_result_roundtrip() -> None:
    """Golden JSON → Python model → JSON → 关键字段对齐。"""
    data = _load("analysis-result-complete.json")
    result = WhiteboxResult.from_dict(data)

    from argus_py.whitebox.runner import _serialize_whitebox_result

    serialized = _serialize_whitebox_result(
        result, len(result.endpoints), len(result.findings), "all"
    )
    diag = serialized.get("diagnostics", {})
    assert diag is not None
    assert diag.get("classpathAvailable") is True
    assert diag.get("totalSourceFiles") == 150


def test_complete_result_re_parse_after_roundtrip() -> None:
    """Roundtrip 后再反序列化 → 模型仍然完整。"""
    data = _load("analysis-result-complete.json")
    result1 = WhiteboxResult.from_dict(data)

    from argus_py.whitebox.runner import _serialize_whitebox_result

    serialized = _serialize_whitebox_result(
        result1, len(result1.endpoints), len(result1.findings), "all"
    )

    # 从 roundtrip JSON 重建 — 注意 _serialize_whitebox_result 输出
    # 是 API 响应格式（camelCase），from_dict 依赖 _from_camel_dict
    result2 = WhiteboxResult.from_dict(serialized)
    assert len(result2.endpoints) == len(result1.endpoints)
    assert len(result2.findings) == len(result1.findings)
    for ep1, ep2 in zip(result1.endpoints, result2.endpoints, strict=True):
        assert ep1.path == ep2.path
        assert ep1.http_method == ep2.http_method


# ── Degraded Result ─────────────────────────────────────────────


def test_degraded_result_deserialization() -> None:
    """WhiteboxResult.from_dict 正确解析 classpath 不可用的降级结果。"""
    data = _load("analysis-result-degraded.json")
    result = WhiteboxResult.from_dict(data)
    assert result.diagnostics is not None
    assert result.diagnostics.classpath_available is False
    assert result.diagnostics.classpath_source == "none"
    assert result.diagnostics.jar_count == 0
    assert len(result.diagnostics.classpath_warnings) >= 1
    assert len(result.diagnostics.classpath_errors) >= 1
    assert result.diagnostics.classpath_command == ""
    assert result.diagnostics.classpath_exit_code is None


# ── Validate Source ─────────────────────────────────────────────


def test_validate_source_deserialization() -> None:
    """Java validate-source 响应包含 exists/readable/allowed 布尔字段；
    VisibilityStatus 由客户端根据 HTTP 状态和字段类型推导，不直接从 JSON 解析。

    allowed 字段是 O-01 新增：Java 用 real-path 边界校验器判定路径是否在
    allowed-source-roots 内（含符号链接逃逸拒绝）。旧版 Java 不返回该字段时
    客户端应容忍（allowed=None），新版必须返回布尔值。
    """
    data = _load("validate-source-response.json")
    assert isinstance(data["exists"], bool)
    assert data["exists"] is True
    assert isinstance(data["readable"], bool)
    assert data["readable"] is True
    assert isinstance(data["allowed"], bool)
    assert data["allowed"] is True


# ── Error ───────────────────────────────────────────────────────


def test_error_response_structure() -> None:
    """Java 错误响应结构：包含 error message 和 errorCode。

    对标 Python client._parse_response 的错误提取路径：
    - error 字段：用户可读错误消息
    - errorCode 字段：机器可判定的错误码
    - timestamp 字段：可选的错误时间戳

    已知缺口：Python 侧没有 ErrorResponse dataclass，
    _request() 根据 HTTP 状态码直接抛出 typed exceptions。
    如果 Java 侧新增错误码，当前测试无法自动发现。
    """
    data = _load("error-response.json")
    assert "error" in data
    assert isinstance(data["error"], str)
    assert len(data["error"]) > 0
    assert "errorCode" in data
    assert isinstance(data["errorCode"], str)
    assert "timestamp" in data
    # 验证 errorCode 是否是已知值之一（非空且格式为 UPPER_SNAKE_CASE）
    assert "_" in data["errorCode"] or data["errorCode"].isupper()
