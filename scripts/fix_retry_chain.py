"""一次性历史数据修复：推断重试链父子关系并统一重试任务名称。

背景：重试链字段 ``retry_parent_task_id`` 是后续版本新增的。历史数据里由旧
逻辑创建的重试任务（``execution_attempt > 1``）没有父链记录，且名称可能为空
或带旧「-重试」后缀。本脚本：

1. 推断重试链父子关系并写入 ``retry_parent_task_id``：
   - 同 ``project_id`` + 同 ``task_type`` + 同 ``goal``
   - 子任务 attempt 恰比父任务大 1
   - 子任务创建时间晚于父任务
2. 将重试任务名称统一为**重试链根任务的基础名**（链上名称一致；空名回退为
   根任务 task_id 后 8 位）。

安全策略：

- 默认 ``--dry-run`` 只打印将做的修改；确认后加 ``--apply`` 才写库。
- 写库前先用 SQLite 在线备份到 ``outputs/backups/``。
- 只更新"空名 / 自身 task_id 兜底 / 旧 ``-重试`` 后缀"的重试任务名称；
  疑似用户手动改过的名称保留并打印警告，不做覆盖。

用法（项目根目录执行）：

    python scripts/fix_retry_chain.py            # dry-run，预览推断结果
    python scripts/fix_retry_chain.py --apply    # 备份后实际修复
    python scripts/fix_retry_chain.py --db path  # 指定数据库

退出码 0 = 全部成功；1 = 有跳过项（如未推断出的重试任务）；2 = 参数/IO 错误。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 不引入 argus_py 模块，保持脚本可独立运行（同 scripts/backup_db.py 约定）。
DEFAULT_DB = Path("outputs/data/argus.db")
BACKUP_DIR = Path("outputs/backups")

_TASK_COLUMNS = (
    "task_id",
    "project_id",
    "task_type",
    "goal",
    "name",
    "execution_attempt",
    "retry_parent_task_id",
    "created_at",
)


# ── 纯逻辑（可导入测试） ─────────────────────────────────────────────────────


def _base_name(row: dict[str, Any]) -> str:
    """任务的基础名：name 非空用 name（去空白），否则用 task_id 后 8 位。"""
    raw = (row["name"] or "").strip()
    return raw or row["task_id"][-8:]


def infer_retry_parents(rows: list[dict[str, Any]]) -> dict[str, str]:
    """推断历史重试链的父子映射，返回 ``{child_task_id: parent_task_id}``。

    已存在 ``retry_parent_task_id`` 的保留；缺失的按同分组 + attempt 连续 +
    创建时间先后推断。返回的 dict 合并两者，child 键唯一。
    """
    parents: dict[str, str] = {}
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        if row["retry_parent_task_id"]:
            parents[row["task_id"]] = row["retry_parent_task_id"]
        key = (row["project_id"], row["task_type"], row["goal"])
        groups.setdefault(key, []).append(row)

    for group in groups.values():
        for child in group:
            if child["execution_attempt"] <= 1 or child["task_id"] in parents:
                continue
            candidates = [
                p
                for p in group
                if p["execution_attempt"] == child["execution_attempt"] - 1
                and p["created_at"] < child["created_at"]
            ]
            if len(candidates) == 1:
                parent = candidates[0]
            elif len(candidates) > 1:
                # 多个候选（同分组多代任务）：取创建时间最接近的（重试通常紧随失败）。
                parent = min(
                    candidates,
                    key=lambda p: abs(_parse_ts(p["created_at"]) - _parse_ts(child["created_at"])),
                )
            else:
                continue
            parents[child["task_id"]] = parent["task_id"]
    return parents


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # created_at 异常时退化为一个恒等序，保证比较不崩溃。
        return datetime.fromisoformat("1970-01-01T00:00:00+00:00")


def root_base_name(
    task_id: str,
    parents: dict[str, str],
    rows_by_id: dict[str, dict[str, Any]],
) -> str:
    """沿重试链回溯到根任务，返回根任务的基础名（链上名称统一）。"""
    seen: set[str] = set()
    current = task_id
    while current in parents and current not in seen:
        seen.add(current)
        current = parents[current]
    return _base_name(rows_by_id[current])


def plan_fixes(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """计算修复计划。

    返回 ``(fixes, warnings)``：
    - ``fixes`` 每项为 ``{task_id, field, old, new, reason}``，按 ``UPDATE``
      可直接执行。
    - ``warnings`` 为未能推断/保留用户改名的说明，仅提示。
    """
    parents = infer_retry_parents(rows)
    rows_by_id = {row["task_id"]: row for row in rows}
    fixes: list[dict[str, Any]] = []
    warnings: list[str] = []

    for child_id, parent_id in parents.items():
        child = rows_by_id[child_id]
        if child["execution_attempt"] <= 1:
            continue
        # 1) 补父链
        if not child["retry_parent_task_id"]:
            fixes.append(
                {
                    "task_id": child_id,
                    "field": "retry_parent_task_id",
                    "old": None,
                    "new": parent_id,
                    "reason": f"推断父任务 {parent_id}（同分组 + attempt 连续 + 时间先后）",
                }
            )
        # 2) 统一名称为根基础名
        target = root_base_name(child_id, parents, rows_by_id)
        current = (child["name"] or "").strip()
        parent_base = _base_name(rows_by_id[parent_id])
        if current == target:
            continue
        if not current or current == child["task_id"][-8:] or current == f"{parent_base}-重试":
            fixes.append(
                {
                    "task_id": child_id,
                    "field": "name",
                    "old": child["name"],
                    "new": target,
                    "reason": f"统一为根任务基础名 {target}",
                }
            )
        else:
            warnings.append(
                f"任务 {child_id} 名称「{current}」疑似手动修改，跳过名称更新（父链已修复）"
            )
    return fixes, warnings


# ── 执行 ─────────────────────────────────────────────────────────────────────


def _read_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT {', '.join(_TASK_COLUMNS)} FROM tasks ORDER BY created_at")
    rows = [dict(row) for row in cur.fetchall()]
    # 兼容历史库把 execution_attempt 存为 TEXT 的情况，统一转为 int。
    for row in rows:
        row["execution_attempt"] = int(row["execution_attempt"])
    return rows


def _online_backup(db: Path) -> Path:
    """SQLite 在线备份，返回备份路径。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKUP_DIR / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / db.name
    src_conn = sqlite3.connect(db)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return dst


def _apply_fixes(db: Path, fixes: list[dict[str, Any]]) -> int:
    """事务执行修复计划，返回受影响行数。"""
    backup = _online_backup(db)
    print(f"[备份] 数据库已备份 → {backup}")

    conn = sqlite3.connect(db)
    try:
        with conn:
            for fix in fixes:
                conn.execute(
                    f"UPDATE tasks SET {fix['field']} = ? WHERE task_id = ?",
                    (fix["new"], fix["task_id"]),
                )
    finally:
        conn.close()
    return len(fixes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="修复历史重试链：推断父链 + 统一名称。")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"数据库路径（默认 {DEFAULT_DB}）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际写库（默认只 dry-run 预览；写库前自动备份）",
    )
    args = parser.parse_args(argv)

    db: Path = args.db.resolve()
    if not db.exists():
        print(f"[错误] 数据库不存在：{db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    try:
        rows = _read_rows(conn)
    finally:
        conn.close()

    fixes, warnings = plan_fixes(rows)

    print(f"共 {len(rows)} 个任务，计划 {len(fixes)} 处修复：")
    for fix in fixes:
        print(
            f"  - {fix['task_id']}: {fix['field']} "
            f"「{fix['old']}」→「{fix['new']}」（{fix['reason']}）"
        )
    for warning in warnings:
        print(f"  [跳过] {warning}", file=sys.stderr)

    if not fixes:
        print("[OK] 无需修复。")
        return 0

    if not args.apply:
        print("\n（dry-run：未写库。确认无误后加 --apply 执行）")
        return 0

    applied = _apply_fixes(db, fixes)
    print(f"[OK] 已修复 {applied} 处。")
    if warnings:
        return 1  # 有跳过项，提示人工核对
    return 0


if __name__ == "__main__":
    sys.exit(main())
