"""运维脚本契约测试：backup_db / cleanup_outputs。

不依赖项目业务代码，独立验证脚本行为，确保运维场景下"只装 Python"也能跑。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest


def _load_script(name: str) -> types.ModuleType:
    """直接 import scripts 目录下的脚本模块。"""
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_argus_scripts.{name}", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backup_db = _load_script("backup_db")
cleanup_outputs = _load_script("cleanup_outputs")


# ── backup_db ──────────────────────────────────────────────────────────────


def _seed_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (name) VALUES ('one'), ('two')")
        conn.commit()
    finally:
        conn.close()


class TestBackupDb:
    def test_backup_creates_dest_with_db_copy(self, tmp_path: Path) -> None:
        db = tmp_path / "src" / "argus.db"
        _seed_db(db)

        code = backup_db.main(
            [
                "--db",
                str(db),
                "--key",
                str(tmp_path / "nonexistent.key"),
                "--dest",
                str(tmp_path / "backups"),
            ]
        )
        assert code == 0

        backups = list((tmp_path / "backups").iterdir())
        assert len(backups) == 1
        copied = backups[0] / "argus.db"
        assert copied.exists()

        # 备份出的 DB 可以正常打开且数据一致
        conn = sqlite3.connect(copied)
        try:
            rows = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()
            assert rows[0] == 2
        finally:
            conn.close()

    def test_backup_copies_fernet_key_when_present(self, tmp_path: Path) -> None:
        db = tmp_path / "argus.db"
        _seed_db(db)
        key = tmp_path / "config" / ".fernet_key"
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_bytes(b"fake-key-bytes")

        code = backup_db.main(
            ["--db", str(db), "--key", str(key), "--dest", str(tmp_path / "backups")]
        )
        assert code == 0

        backups = list((tmp_path / "backups").iterdir())
        copied_key = backups[0] / ".fernet_key"
        assert copied_key.exists()
        assert copied_key.read_bytes() == b"fake-key-bytes"

    def test_missing_db_returns_error(self, tmp_path: Path) -> None:
        code = backup_db.main(
            [
                "--db",
                str(tmp_path / "missing.db"),
                "--key",
                str(tmp_path / "nope"),
                "--dest",
                str(tmp_path / "backups"),
            ]
        )
        assert code == 2
        assert not (tmp_path / "backups").exists()

    def test_keep_prunes_old_backups(self, tmp_path: Path) -> None:
        db = tmp_path / "argus.db"
        _seed_db(db)
        dest = tmp_path / "backups"

        # 先伪造三个历史备份目录
        for stamp in ("20240101T000000Z", "20240601T000000Z", "20241201T000000Z"):
            (dest / stamp).mkdir(parents=True)
            (dest / stamp / "argus.db").write_bytes(b"placeholder")

        # 跑一次 backup，--keep 2 应只保留最近 2 个（新备份 + 最近的旧备份）
        code = backup_db.main(
            ["--db", str(db), "--key", str(tmp_path / "nope"), "--dest", str(dest), "--keep", "2"]
        )
        assert code == 0

        remaining = sorted(p.name for p in dest.iterdir())
        assert len(remaining) == 2
        # 最老的两个应被删除
        assert "20240101T000000Z" not in remaining
        assert "20240601T000000Z" not in remaining


# ── cleanup_outputs ────────────────────────────────────────────────────────


def _make_file(path: Path, age_days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    ts = time.time() - age_days * 86400
    import os

    os.utime(path, (ts, ts))
    return path


class TestCleanupOutputs:
    def test_removes_old_files_in_target_dirs(self, tmp_path: Path) -> None:
        root = tmp_path / "outputs"
        old = _make_file(root / "logs" / "old.log", age_days=40)
        new = _make_file(root / "logs" / "new.log", age_days=1)

        code = cleanup_outputs.main(["--root", str(root), "--days", "30", "--targets", "logs"])
        assert code == 0
        assert not old.exists()
        assert new.exists()

    def test_dry_run_keeps_files(self, tmp_path: Path) -> None:
        root = tmp_path / "outputs"
        old = _make_file(root / "screenshots" / "old.png", age_days=100)

        code = cleanup_outputs.main(
            ["--root", str(root), "--days", "30", "--targets", "screenshots", "--dry-run"]
        )
        assert code == 0
        assert old.exists()  # dry-run 不真删

    def test_protected_targets_rejected(self, tmp_path: Path) -> None:
        """data / backups 目录禁止通过本脚本清理。"""
        code = cleanup_outputs.main(["--root", str(tmp_path), "--days", "30", "--targets", "data"])
        assert code == 2

    def test_missing_target_dir_is_skipped(self, tmp_path: Path) -> None:
        """目标子目录不存在 → 安静跳过，不报错。"""
        code = cleanup_outputs.main(
            ["--root", str(tmp_path), "--days", "30", "--targets", "logs,nonexistent"]
        )
        assert code == 0

    @pytest.mark.parametrize("days", [0, -1])
    def test_invalid_days_rejected(self, tmp_path: Path, days: int) -> None:
        code = cleanup_outputs.main(["--root", str(tmp_path), "--days", str(days)])
        assert code == 2

    def test_empty_subdirs_pruned_after_cleanup(self, tmp_path: Path) -> None:
        root = tmp_path / "outputs"
        nested = root / "temp" / "task-001" / "step-1"
        _make_file(nested / "trace.json", age_days=60)

        code = cleanup_outputs.main(["--root", str(root), "--days", "30", "--targets", "temp"])
        assert code == 0
        assert not (nested / "trace.json").exists()
        # 清理后空目录也应被收
        assert not (root / "temp" / "task-001").exists()
        # 但顶层 target 目录本身保留
        assert (root / "temp").exists()
