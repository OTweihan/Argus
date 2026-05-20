"""Argus 数据库在线热备份脚本。

私网部署语境下生产数据丢失没人救你；本脚本提供安全的在线备份能力：

- 使用 SQLite ``Connection.backup()`` 在线热拷贝，不需要停服（连接通过 WAL
  与运行中实例共享，不会撕裂正在写入的事务）。
- 同时备份 ``config/.fernet_key``——缺它的备份解不开 model_configs 里的
  API Key 密文。
- 输出按 UTC 时间戳分目录，方便保留多代版本。

用法（项目根目录执行）：

    python scripts/backup_db.py                 # 默认输出到 outputs/backups/
    python scripts/backup_db.py --dest /mnt/x   # 指定外置盘
    python scripts/backup_db.py --keep 7        # 自动只保留最近 7 个备份

退出码 0 = 成功；非 0 = 失败，详见 stderr。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# 不引入 argus_py 任何模块，避免备份脚本依赖项目代码可运行；运维场景下
# 经常只有 Python 解释器而不一定 pip install 了项目。
DEFAULT_DB = Path("outputs/data/argus.db")
DEFAULT_KEY = Path("config/.fernet_key")
DEFAULT_DEST = Path("outputs/backups")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _online_sqlite_backup(src: Path, dst: Path) -> None:
    """用 SQLite 自带的在线备份 API 复制数据库（含 WAL 中未 checkpoint 的数据）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(src)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _human_size(num_bytes: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} {units[-1]}"


def _prune_old_backups(dest_root: Path, keep: int) -> list[Path]:
    """按时间戳目录名排序，保留最新 ``keep`` 个，删除其余。"""
    if keep <= 0:
        return []
    candidates = sorted(
        (p for p in dest_root.iterdir() if p.is_dir() and p.name.endswith("Z")),
        key=lambda p: p.name,
    )
    to_delete = candidates[:-keep] if len(candidates) > keep else []
    for path in to_delete:
        shutil.rmtree(path, ignore_errors=True)
    return to_delete


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup Argus SQLite database online.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"源数据库路径（默认 {DEFAULT_DB}）",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=DEFAULT_KEY,
        help=f"Fernet 密钥路径（默认 {DEFAULT_KEY}），不存在时跳过",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"备份根目录（默认 {DEFAULT_DEST}）",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=0,
        help="只保留最近 N 个备份；0 表示不清理（默认）",
    )
    args = parser.parse_args(argv)

    src_db: Path = args.db.resolve()
    if not src_db.exists():
        print(f"[错误] 数据库不存在：{src_db}", file=sys.stderr)
        return 2

    stamp = _utc_stamp()
    dest_root: Path = args.dest.resolve()
    backup_dir = dest_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_db = backup_dir / src_db.name
    try:
        _online_sqlite_backup(src_db, backup_db)
    except sqlite3.Error as exc:
        print(f"[错误] SQLite 在线备份失败：{exc}", file=sys.stderr)
        shutil.rmtree(backup_dir, ignore_errors=True)
        return 3

    db_size = backup_db.stat().st_size
    print(f"[OK] 数据库已备份 → {backup_db}（{_human_size(db_size)}）")

    key_src: Path = args.key.resolve()
    if key_src.exists():
        key_dst = backup_dir / key_src.name
        shutil.copy2(key_src, key_dst)
        print(f"[OK] Fernet 密钥已备份 → {key_dst}")
    else:
        print(f"[警告] 未找到 Fernet 密钥：{key_src}（如有加密 API Key 将无法解密）")

    if args.keep > 0:
        pruned = _prune_old_backups(dest_root, args.keep)
        if pruned:
            print(f"[清理] 删除 {len(pruned)} 个过期备份：")
            for path in pruned:
                print(f"  - {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
