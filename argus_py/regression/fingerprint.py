"""问题稳定指纹：跨批次比较键。

指纹口径（v1，见回归闭环计划 §3.3）：

    task_type + finding_type + severity + normalize(title) + normalize(resource_location)

- 标题做空白折叠与大小写归一；
- 资源位置去除易变行号后缀（``file.py:123`` / ``File.java:45-47``）；
  URL 形式的位置只去 ``#fragment`` 与末尾斜杠，不拆查询串；
- 描述、finding_id、截图路径、created_at 不参与指纹——避免运行产物
  差异造成误报。

版本化（``FINGERPRINT_VERSION``）：规范化规则未来调整时递增版本并写入批次
汇总，历史批次的差异解释以当时版本为准。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from argus_py.core.enums import FindingSeverity, FindingType, TaskType

FINGERPRINT_VERSION = "v1"

# 行号后缀：path/file.py:123、File.java:45-47（仅非 URL 文本）
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
# URL fragment
_FRAGMENT_RE = re.compile(r"#.*$")

_FINGERPRINT_HEX_LEN = 16


def normalize_title(title: str) -> str:
    """标题规范化：折叠连续空白 + casefold。"""
    return " ".join((title or "").split()).casefold()


def normalize_location(location: str | None) -> str:
    """资源位置规范化。

    - 非 URL 文本：反复剥离行号后缀（``:123`` / ``:12-34``），再折叠空白；
    - URL（含 ``://``）：去掉 ``#fragment``、去末尾 ``/``；保留查询串与路径大小写。
    """
    value = (location or "").strip()
    if not value:
        return ""
    if "://" in value:
        return _FRAGMENT_RE.sub("", value).rstrip("/")
    stripped = value
    while True:
        candidate = _LINE_SUFFIX_RE.sub("", stripped)
        if candidate == stripped:
            break
        stripped = candidate
    return " ".join(stripped.split())


@dataclass(frozen=True)
class FingerprintedFinding:
    """带稳定指纹的发现项视图（参与差异计算的最小字段集）。"""

    fingerprint: str
    title: str
    severity: str
    finding_type: str
    location: str | None
    task_id: str | None = None
    case_id: str | None = None


def compute_fingerprint(
    task_type: TaskType | str,
    finding_type: FindingType | str,
    severity: FindingSeverity | str,
    title: str,
    location: str | None = None,
) -> str:
    """计算问题稳定指纹。"""
    parts = (
        str(getattr(task_type, "value", task_type)),
        str(getattr(finding_type, "value", finding_type)),
        str(getattr(severity, "value", severity)),
        normalize_title(title),
        normalize_location(location),
    )
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:_FINGERPRINT_HEX_LEN]
