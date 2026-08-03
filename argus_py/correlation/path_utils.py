"""阶段三：黑白盒关联 — 路径规范化与脱敏工具。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

NORMALIZATION_VERSION = "v1"
MATCHER_VERSION = "v1"
MAX_PATH_LENGTH = 512

# 矩阵参数正则（;jsessionid=xxx 等）
_MATRIX_PARAM_RE = re.compile(r";[^/]+")

# 多个连续斜杠
_MULTISLASH_RE = re.compile(r"/{2,}")

# 需要脱敏的路径段模式
_TOKEN_PATTERNS = [
    (re.compile(r"^[0-9a-fA-F]{32,}$"), "{token}"),  # 长 hex
    (re.compile(r"^[A-Za-z0-9+/=]{40,}$"), "{token}"),  # base64
    (
        re.compile(
            r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.IGNORECASE
        ),
        "{uuid}",
    ),
    (re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"), "{email}"),  # email
]


def normalize_for_matching(
    url: str,
    context_path: str = "",
    strip_prefixes: list[str] | None = None,
    prepend_prefix: str = "",
) -> str:
    """从 URL 提取规范化路径用于端点匹配。

    规则：去 query/fragment、重复斜杠合并、尾斜杠处理、
    matrix param 移除（;jsessionid=...）、百分号编码保留不解码、
    大小写保留原文、Unicode NFC。
    """
    parsed = urlparse(url)
    path = parsed.path

    # 重复斜杠合并
    path = _MULTISLASH_RE.sub("/", path)

    # Matrix param 移除
    path = _MATRIX_PARAM_RE.sub("", path)

    # 尾斜杠：去掉（根路径保留 /）
    if path != "/":
        path = path.rstrip("/")

    # 空路径 → /
    if not path:
        path = "/"

    # Unicode NFC
    path = unicodedata.normalize("NFC", path)

    # Context path 去除
    if context_path and path.startswith(context_path):
        path = path[len(context_path) :] or "/"

    # 网关前缀剥离（按段边界最长前缀优先）
    if strip_prefixes:
        path, _ = strip_longest_segment_prefix(path, strip_prefixes)

    # 前缀重挂
    if prepend_prefix:
        path = prepend_prefix.rstrip("/") + path

    return path


def sanitize_for_display(normalized_path: str) -> str:
    """将规范化路径中的敏感段脱敏为通用占位符。"""
    segments = normalized_path.split("/")
    sanitized: list[str] = []
    for seg in segments:
        replaced = False
        for pattern, replacement in _TOKEN_PATTERNS:
            if pattern.match(seg):
                sanitized.append(replacement)
                replaced = True
                break
        if not replaced:
            sanitized.append(seg)
    return "/".join(sanitized)


def compute_path_segments(path: str) -> list[str]:
    """返回路径段列表（空段过滤）。"""
    return [s for s in path.split("/") if s]


def extract_origin(url: str) -> str:
    """提取并规范化 origin：默认端口归一化、Host 小写、IPv6 方括号。"""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host: str = parsed.hostname or ""
    host = host.lower().strip("[]")  # IPv6 去方括号后小写
    port: int | None = getattr(parsed, "port", None)

    # 默认端口归一化
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    if port is not None:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def is_path_too_long(normalized_path: str, max_length: int = MAX_PATH_LENGTH) -> bool:
    """判断路径是否超过最大长度限制。"""
    return len(normalized_path) > max_length


def compute_config_digest(
    matcher_version: str,
    normalization_version: str,
    strip_prefixes: list[str] | None = None,
    context_path: str = "",
    prepend_prefix: str = "",
) -> str:
    """计算关联配置指纹，用于幂等去重。"""
    parts = [
        matcher_version,
        normalization_version,
        ",".join(sorted(strip_prefixes or [])),
        context_path,
        prepend_prefix,
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def strip_longest_segment_prefix(path: str, prefixes: list[str]) -> tuple[str, str | None]:
    """按路径段边界匹配最长前缀。

    /api/order 不匹配 /api/orders/1。
    多个 prefix 同时命中时选最长段前缀。
    返回（处理后的路径, 命中的前缀或 None）。
    """
    if not prefixes or not path:
        return path, None

    segments = compute_path_segments(path)

    best_prefix: str | None = None
    best_seg_count = 0

    for prefix in prefixes:
        prefix_segments = compute_path_segments(prefix)
        if len(prefix_segments) > len(segments):
            continue
        # 逐段匹配
        if segments[: len(prefix_segments)] == prefix_segments:
            if len(prefix_segments) > best_seg_count:
                best_seg_count = len(prefix_segments)
                best_prefix = prefix

    if best_prefix is None:
        return path, None

    remaining = "/" + "/".join(segments[best_seg_count:]) if best_seg_count < len(segments) else "/"
    return remaining, best_prefix
