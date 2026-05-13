"""LLM 追踪脱敏单测。"""

from __future__ import annotations

from typing import Any

from argus_py.observability.llm_trace import _redact_trace_data


class TestRedactTraceData:
    """_redact_trace_data 递归脱敏测试。"""

    def test_plain_dict_passthrough(self) -> None:
        data = {"phase": "planner", "model": "qwen"}
        assert _redact_trace_data(data) == data

    def test_sensitive_key_at_root(self) -> None:
        data = {"api_key": "sk-abc123", "goal": "test"}
        result = _redact_trace_data(data)
        assert result["api_key"] == "***"
        assert result["goal"] == "test"

    def test_nested_dict_sensitive_key(self) -> None:
        data = {"input_payload": {"password": "secret123", "goal": "test"}}
        result = _redact_trace_data(data)
        assert result["input_payload"]["password"] == "***"
        assert result["input_payload"]["goal"] == "test"

    def test_list_of_dicts_sensitive_key(self) -> None:
        """list 内的 dict 敏感字段应被脱敏。"""
        data = {
            "history": [
                {"action": "goto", "params": {"password": "secret123"}},
                {"action": "click", "params": {"url": "http://example.com"}},
            ]
        }
        result = _redact_trace_data(data)
        assert result["history"][0]["params"]["password"] == "***"
        assert result["history"][0]["action"] == "goto"
        assert result["history"][1]["params"]["url"] == "http://example.com"

    def test_token_in_list_value_not_masked(self) -> None:
        """token 作为值不应脱敏，只有作为 key 才脱敏。"""
        data = {"messages": [{"role": "user", "content": "my token is abc"}]}
        result = _redact_trace_data(data)
        assert result["messages"][0]["content"] == "my token is abc"

    def test_token_usage_safelisted(self) -> None:
        """safelist 中的诊断字段应原样保留。"""
        data = {"token_usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200}}
        result = _redact_trace_data(data)
        assert result["token_usage"] == {
            "prompt_tokens": 150,
            "completion_tokens": 50,
            "total_tokens": 200,
        }

    def test_nested_list_safeguard(self) -> None:
        """深层嵌套 list+dict 组合。"""
        data = {
            "input_payload": {
                "history": [
                    {
                        "step": 1,
                        "params": {"token": "jwt-xyz", "password": "hunter2"},
                        "result": "success",
                    }
                ]
            }
        }
        result = _redact_trace_data(data)
        entry = result["input_payload"]["history"][0]
        assert entry["params"]["token"] == "***"
        assert entry["params"]["password"] == "***"
        assert entry["step"] == 1
        assert entry["result"] == "success"

    def test_mixed_list(self) -> None:
        """list 内含原始值和 dict。"""
        data = {"tags": ["plain", {"secret": "hidden"}, 42]}
        result = _redact_trace_data(data)
        assert result["tags"][0] == "plain"
        assert result["tags"][1]["secret"] == "***"
        assert result["tags"][2] == 42

    def test_empty_list(self) -> None:
        data: dict[str, Any] = {"history": []}
        assert _redact_trace_data(data) == data

    def test_empty_dict(self) -> None:
        data: dict[str, Any] = {"meta": {}}
        assert _redact_trace_data(data) == data
