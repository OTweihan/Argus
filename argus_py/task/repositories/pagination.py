"""共享游标分页工具（keyset 分页）。

游标编码：``base64(json({"k": [sort_key_values]}))``，对客户端不透明。
解码或校验失败时回退为首页请求（仍计算 total）。

``AnalysisRunRepository._paginated_query`` 与
``FindingRepository.list_by_analysis_id`` 等分页查询共用此实现，
避免游标语义在多处手写后行为分化。
"""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Sequence
from typing import Any

MAX_CURSOR_LIMIT = 200


def encode_cursor(keys: Sequence[Any]) -> str:
    """把排序键值编码为不透明游标。"""
    payload = json.dumps({"k": list(keys)}).encode()
    return base64.urlsafe_b64encode(payload).decode()


def decode_cursor(cursor: str | None, expected_len: int) -> list[Any] | None:
    """解码并校验游标排序键；非法时返回 None（调用方回退首页）。

    键数量必须与排序列数一致；元素必须为标量（str/int/float，显式排除
    bool/None/容器），否则长度合规但元素非标量的游标会在 SQLite 参数
    绑定时抛 500，而不是回退首页。
    """
    if not cursor:
        return None
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor).decode())
        keys = decoded["k"]
        if not isinstance(keys, list) or len(keys) != expected_len:
            raise ValueError("cursor keys must match order columns")
        if any(not isinstance(k, (str, int, float)) or isinstance(k, bool) for k in keys):
            raise ValueError("cursor keys must be scalar")
        return keys
    except Exception:
        return None


def cursor_paginate(
    conn: sqlite3.Connection,
    table: str,
    *,
    order: str,
    where: str,
    params: Sequence[Any],
    cursor: str | None = None,
    limit: int = 100,
) -> tuple[list[sqlite3.Row], str | None, int | None, bool]:
    """通用 keyset 游标分页。

    - ``order`` 形如 ``"created_at DESC, finding_id ASC"``；每列方向决定该列
      的游标比较符（ASC → 大于，DESC → 小于），混合方向排序同样正确。
    - 仅在无有效游标（首页或非法游标回退首页）时计算 total；后续 cursor 页
      返回 None，由客户端复用首屏 total，避免每页重复全表/索引 COUNT。
    - limit 钳制到 :data:`MAX_CURSOR_LIMIT`；多取一行判定 has_more。

    返回 ``(rows, next_cursor, total, has_more)``，rows 为原始 ``sqlite3.Row``
    （依赖连接的 Row row_factory），由调用方负责行映射。
    """
    parsed_order: list[tuple[str, bool]] = []
    for part in order.split(","):
        tokens = part.strip().split()
        col = tokens[0]
        is_desc = len(tokens) > 1 and tokens[1].upper() == "DESC"
        parsed_order.append((col, is_desc))

    cursor_keys = decode_cursor(cursor, len(parsed_order))
    effective_params = list(params)
    sql = f"SELECT * FROM {table} WHERE {where}"

    # total 仅在首屏请求（无有效 cursor）时计算
    total: int | None = None
    if cursor_keys is None:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE {where}",
            effective_params,
        ).fetchone()
        total = row["cnt"] if row else 0

    if cursor_keys is not None:
        # 游标过滤：前缀列相等 + 当前列按方向比较（ASC > / DESC <）
        conds: list[str] = []
        for i, (col, is_desc) in enumerate(parsed_order):
            cond_cols = [f"{parsed_order[j][0]} = ?" for j in range(i)]
            cond_cols.append(f"{col} {'<' if is_desc else '>'} ?")
            conds.append("(" + " AND ".join(cond_cols) + ")")
            effective_params.extend(cursor_keys[: i + 1])
        sql += f" AND ({' OR '.join(conds)})"

    limit = min(limit, MAX_CURSOR_LIMIT)
    sql += f" ORDER BY {order} LIMIT ?"
    rows = conn.execute(sql, [*effective_params, limit + 1]).fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor([last[col] for col, _ in parsed_order])
    return rows, next_cursor, total, has_more
