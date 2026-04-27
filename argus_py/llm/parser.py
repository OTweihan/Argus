"""LLM 响应解析。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _candidate_texts(text: str) -> Iterable[str]:
    """生成可能包含 JSON 的文本片段。"""
    for match in _JSON_BLOCK_RE.finditer(text):
        yield match.group(1).strip()
    stripped = text.strip()
    if stripped:
        yield stripped
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = stripped.find(start_char)
        end = stripped.rfind(end_char)
        if start >= 0 and end > start:
            yield stripped[start : end + 1]


def extract_json_value(text: str) -> Any:
    """从 LLM 文本中提取 JSON 值，支持对象或数组。"""
    decoder = json.JSONDecoder()
    errors: list[str] = []

    for candidate in _candidate_texts(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))

        for index, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
                return value
            except json.JSONDecodeError as exc:
                errors.append(str(exc))

    detail = errors[-1] if errors else "没有找到 JSON 起始符。"
    raise ValueError(f"未能从 LLM 响应中提取有效 JSON：{detail}")


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 文本中提取 JSON 对象。"""
    value = extract_json_value(text)
    if not isinstance(value, dict):
        raise ValueError("LLM JSON 响应不是对象。")
    return value


def validate_required_keys(data: dict[str, Any], required_keys: Iterable[str]) -> None:
    """校验 JSON 对象必填字段。"""
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(f"LLM JSON 响应缺少必填字段：{', '.join(missing)}")
