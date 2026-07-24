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

清理策略：

- logs 目标内部按文件路径匹配差异化保留期：
  * dev/<run-id>/**         — 14 天
  * runtime/python/轮转文件   — 按类别（audit 180 天、access 14 天、error 30 天、普通 30 天）
  * 四个当前主日志文件         — 永不删除（大小由 RotatingFileHandler 控制）
  * 未分类日志文件              — 回退到 --days（默认 30 天）
- 其他目标（screenshots、temp、reports、traces）统一使用 --days（默认 30 天）

退出码 0 = 成功；1 = 部分文件删除失败；2 = 参数错误。
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

# 与 core/paths.py 默认布局对齐，但脚本独立运行不 import 业务代码。
DEFAULT_OUTPUTS = Path("outputs")
DEFAULT_TARGETS = ("screenshots", "logs", "temp", "reports", "traces")

# DB 与 backups 永远不清
PROTECTED = frozenset({"data", "backups"})

# ── 类型定义 ─────────────────────────────────────────────────────────────

RetentionDecision = tuple[str, int]
RetentionResolver = Callable[[Path], RetentionDecision | None]
# None → 该文件受保护，跳过不参与清理

# ── 日志类别保留规则 ─────────────────────────────────────────────────────

# 当前主日志文件永不被清理脚本删除（大小由 RotatingFileHandler 控制）
_ACTIVE_RUNTIME_LOGS: frozenset[str] = frozenset(
    {
        "runtime/python/argus.log",
        "runtime/python/argus.error.log",
        "runtime/python/argus.audit.log",
        "runtime/python/argus.access.log",
    }
)

# 轮转文件基名 → (类别名称, 保留天数)
# 每个 basename 之间不存在前缀竞争，顺序不影响匹配正确性。
_RUNTIME_BASE_RULES: tuple[tuple[str, str, int], ...] = (
    ("argus.audit.log", "runtime-audit", 180),
    ("argus.access.log", "runtime-access", 14),
    ("argus.error.log", "runtime-error", 30),
    ("argus.log", "runtime-general", 30),
)

# 日志目录结构节点：清理后即使为空也保留，避免破坏稳定布局
_PRESERVED_LOG_DIRS: frozenset[str] = frozenset(
    {
        "runtime",
        "runtime/python",
        "dev",
    }
)


def _match_rotated_log(filename: str) -> RetentionDecision | None:
    """匹配 basename.N 或 basename.N.gz 格式的轮转日志文件。

    返回 (类别名称, 保留天数)，不匹配则返回 None。
    """
    for basename, category, days in _RUNTIME_BASE_RULES:
        rotation_prefix = f"{basename}."
        if not filename.startswith(rotation_prefix):
            continue

        num_part = filename[len(rotation_prefix) :]
        # 支持 .N 和 .N.gz 格式
        if num_part.endswith(".gz"):
            num_part = num_part[:-3]

        if num_part.isdigit():
            return category, days

    return None


def _resolve_log_retention(
    file_path: Path,
    logs_root: Path,
    fallback_days: int,
) -> RetentionDecision | None:
    """返回 (类别名称, 保留天数)；None 表示受保护，跳过。"""
    try:
        relative_path = file_path.relative_to(logs_root).as_posix()
    except ValueError:
        return None

    # 主日志文件受保护，永不被清理
    if relative_path in _ACTIVE_RUNTIME_LOGS:
        return None

    # runtime/python/ 下的文件
    if relative_path.startswith("runtime/python/"):
        filename = relative_path.removeprefix("runtime/python/")
        rotated = _match_rotated_log(filename)
        if rotated is not None:
            return rotated
        # 非标准轮转文件（如 argus.audit.log.backup）回退到 --days
        return ("fallback", fallback_days)

    # dev 会话目录 — 按文件 mtime 清理，同一 <run-id> 中的文件可能各自到达阈值
    if relative_path.startswith("dev/"):
        return ("dev-session", 14)

    # 未分类文件回退到 --days
    return ("fallback", fallback_days)


def _make_log_retention_resolver(
    logs_root: Path,
    fallback_days: int,
) -> RetentionResolver:
    """创建日志保留策略解析器（避免循环内 lambda 捕获）。"""

    def resolve(file_path: Path) -> RetentionDecision | None:
        return _resolve_log_retention(file_path, logs_root, fallback_days)

    return resolve


# ── 文件遍历与清理 ────────────────────────────────────────────────────────


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


def _purge(
    target: Path,
    *,
    default_days: int,
    dry_run: bool,
    retention_resolver: RetentionResolver | None = None,
    preserve_dirs: frozenset[str] | None = None,
) -> tuple[int, int, int, int]:
    """删除超龄文件，返回 (deleted, freed, skipped, failed)。

    若提供 retention_resolver，每文件调用以获取 (类别, 保留天数)；
    返回 None 则表示该文件受保护，跳过。
    """
    now = time.time()
    deleted = 0
    freed = 0
    skipped = 0
    failed = 0

    for file in _iter_files(target):
        try:
            st = file.stat()
        except OSError as exc:
            print(f"    [跳过] 无法读取文件信息：{file}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        # 解析保留策略 — resolver 返回 None 表示受保护，跳过
        if retention_resolver is not None:
            decision = retention_resolver(file)
            if decision is None:
                continue  # 受保护文件，不计入任何统计
        else:
            decision = ("default", default_days)

        category, retention_days = decision
        cutoff = now - retention_days * 86400
        if st.st_mtime >= cutoff:
            continue

        label = f"[{category}] {retention_days}d"
        print(f"  - {file}  ({_human_size(st.st_size)}) {label}")

        if dry_run:
            deleted += 1
            freed += st.st_size
            continue

        try:
            file.unlink()
            deleted += 1
            freed += st.st_size
        except OSError as exc:
            print(f"    [跳过] 无法删除：{exc}", file=sys.stderr)
            failed += 1

    if not dry_run:
        _remove_empty_dirs(target, preserve=preserve_dirs)
    return deleted, freed, skipped, failed


def _remove_empty_dirs(
    target: Path,
    *,
    preserve: frozenset[str] | None = None,
) -> None:
    """自底向上删除清空后的子目录；target 本身保留。

    ``preserve`` 中给定的相对于 target 的目录名会跳过删除。
    """
    if not target.exists():
        return
    for path in sorted(
        (p for p in target.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        if preserve is not None:
            try:
                rel = path.relative_to(target).as_posix()
            except ValueError:
                continue
            if rel in preserve:
                continue
        try:
            path.rmdir()
        except OSError:
            continue  # 非空 / 权限不足，安静跳过


# ── CLI ───────────────────────────────────────────────────────────────────


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
        help="非 logs 目标的保留天数；对 logs 目标仅作为未分类文件的回退天数（默认 30）",
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

    total_deleted = 0
    total_freed = 0
    total_skipped = 0
    total_failed = 0
    mode = "dry-run" if args.dry_run else "执行"
    print(f"[{mode}] 清理 {root} 下文件")
    for name in targets:
        target_dir = root / name
        if not target_dir.exists():
            print(f"  · 跳过（不存在）：{target_dir}")
            continue
        print(f"  · 扫描：{target_dir}")

        if name == "logs":
            resolver: RetentionResolver | None = _make_log_retention_resolver(target_dir, args.days)
            preserve_dirs: frozenset[str] | None = _PRESERVED_LOG_DIRS
        else:
            resolver = None
            preserve_dirs = None

        deleted, freed, skipped, failed = _purge(
            target_dir,
            default_days=args.days,
            dry_run=args.dry_run,
            retention_resolver=resolver,
            preserve_dirs=preserve_dirs,
        )
        if deleted == 0 and skipped == 0 and failed == 0:
            print("    （无可清理文件）")
        total_deleted += deleted
        total_freed += freed
        total_skipped += skipped
        total_failed += failed

    action = "将删除" if args.dry_run else "已删除"
    print(
        f"[完成] {action} {total_deleted} 个文件，"
        f"释放 {_human_size(total_freed)}，"
        f"跳过 {total_skipped} 个，"
        f"失败 {total_failed} 个"
    )
    return 1 if total_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
