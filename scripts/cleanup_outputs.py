"""清理 Argus outputs 子目录中过期文件。

私网长期部署后 ``outputs/screenshots``、``outputs/temp``、``outputs/logs``
会无限堆积，磁盘很快被吃满。本脚本按文件 mtime 顺序清理超龄文件。

与 ``config/server.yaml`` 的 ``llm_trace.retention_days`` 协同（启动期清 trace）；
本脚本聚焦运维定时任务（cron / 计划任务）能批量删的杂项目录。

用法（项目根目录执行）：

    python scripts/cleanup_outputs.py                # 默认清理 30 天前的文件
    python scripts/cleanup_outputs.py --days 7
    python scripts/cleanup_outputs.py --dry-run      # 预览即将删除的文件
    python scripts/cleanup_outputs.py --targets logs,temp  # 只清指定子目录

退出码 0 = 成功；2 = 参数错误。
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from pathlib import Path

# 与 core/paths.py 默认布局对齐，但脚本独立运行不 import 业务代码。
DEFAULT_OUTPUTS = Path("outputs")
DEFAULT_TARGETS = ("screenshots", "logs", "temp", "reports", "traces")

# DB 与 backups 永远不清；任务级别的报告也很重要，默认放宽到 90 天
PROTECTED = frozenset({"data", "backups"})


def _iter_files(root: Path) -> Iterable[Path]:
    """递归遍历目录下的所有文件（跳过符号链接，避免无意中清理外部数据）。"""
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            yield path


def _human_size(num_bytes: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} {units[-1]}"


def _purge(target: Path, cutoff_ts: float, dry_run: bool) -> tuple[int, int]:
    """删除 ``target`` 下 mtime < cutoff 的文件，返回 (count, freed_bytes)。

    清理后顺手删除空目录（不动 target 自身）。
    """
    removed = 0
    freed = 0
    for file in _iter_files(target):
        try:
            mtime = file.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff_ts:
            continue
        size = file.stat().st_size
        print(f"  - {file}  ({_human_size(size)})")
        if not dry_run:
            try:
                file.unlink()
                removed += 1
                freed += size
            except OSError as exc:
                print(f"    [跳过] 无法删除：{exc}", file=sys.stderr)
        else:
            removed += 1
            freed += size

    if not dry_run:
        _remove_empty_dirs(target)
    return removed, freed


def _remove_empty_dirs(target: Path) -> None:
    """自底向上删除清空后的子目录；target 本身保留。"""
    if not target.exists():
        return
    for path in sorted(
        (p for p in target.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            continue  # 非空 / 权限不足，安静跳过


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Purge stale files from Argus outputs subdirectories."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_OUTPUTS,
        help=f"outputs 根目录（默认 {DEFAULT_OUTPUTS}）",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=",".join(DEFAULT_TARGETS),
        help=f"逗号分隔的子目录列表（默认 {','.join(DEFAULT_TARGETS)}）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="清理 mtime 早于 N 天前的文件（默认 30）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出待删文件，不实际删除",
    )
    args = parser.parse_args(argv)

    if args.days < 1:
        print("[错误] --days 必须 >= 1", file=sys.stderr)
        return 2

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    protected_requested = [t for t in targets if t in PROTECTED]
    if protected_requested:
        print(
            f"[错误] 受保护目录禁止通过本脚本清理：{protected_requested}",
            file=sys.stderr,
        )
        return 2

    root: Path = args.root.resolve()
    cutoff_ts = time.time() - args.days * 86400

    total_removed = 0
    total_freed = 0
    mode = "dry-run" if args.dry_run else "执行"
    print(f"[{mode}] 清理 {root} 下 {args.days} 天前文件")
    for name in targets:
        target = root / name
        if not target.exists():
            print(f"  · 跳过（不存在）：{target}")
            continue
        print(f"  · 扫描：{target}")
        removed, freed = _purge(target, cutoff_ts, args.dry_run)
        if removed == 0:
            print("    （无可清理文件）")
        total_removed += removed
        total_freed += freed

    action = "将删除" if args.dry_run else "已删除"
    print(f"[完成] {action} {total_removed} 个文件，{action[:2]}释放 {_human_size(total_freed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
