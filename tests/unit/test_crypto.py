"""测试 Fernet 密钥启动校验。"""

from __future__ import annotations

import os

import pytest
from argus_py.core.crypto import ensure_fernet_key
from argus_py.core.exceptions import ConfigError
from argus_py.infra.db import _DefaultDBProbe, init_database


def test_ensure_key_when_exists(tmp_path, monkeypatch):
    """key 存在 → 正常返回。"""
    key_file = tmp_path / ".fernet_key"
    key_file.write_bytes(b"existing-key-data")
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))

    ensure_fernet_key()
    assert key_file.exists()
    assert key_file.read_bytes() == b"existing-key-data"


def test_ensure_key_generates_when_missing(tmp_path, monkeypatch):
    """key 不存在、无 DB → 自动生成。"""
    key_file = tmp_path / ".fernet_key"
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))

    ensure_fernet_key()
    assert key_file.exists()
    assert len(key_file.read_bytes()) > 0  # 有效 key


def test_ensure_key_generates_when_db_has_no_encrypted_keys(tmp_path, monkeypatch):
    """key 不存在、DB 无加密记录 → 自动生成。"""
    key_file = tmp_path / ".fernet_key"
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))

    db_path = tmp_path / "empty.db"
    init_database(db_path)
    # 不插入任何 model_configs，所以无加密 key

    ensure_fernet_key(_DefaultDBProbe(db_path))
    assert key_file.exists()


def test_ensure_key_raises_when_db_has_encrypted_keys(tmp_path, monkeypatch):
    """key 不存在、DB 有加密记录 → 抛出 ConfigError。"""
    key_file = tmp_path / ".fernet_key"
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))

    class _AlwaysEncryptedProbe:
        """始终返回 True 的探针。"""

        def has_encrypted_api_keys(self) -> bool:
            return True

    with pytest.raises(ConfigError, match="Fernet 密钥文件"):
        ensure_fernet_key(_AlwaysEncryptedProbe())

    assert not key_file.exists()


@pytest.mark.skipif(os.name != "posix", reason="Windows 的 chmod 仅影响只读位")
def test_generated_key_has_restrictive_permissions(tmp_path, monkeypatch):
    """新生成的 Fernet 密钥在 POSIX 上应为 0o600 防止同机用户读取。"""
    key_file = tmp_path / ".fernet_key"
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))

    ensure_fernet_key()
    assert key_file.exists()
    mode = key_file.stat().st_mode & 0o777
    assert mode == 0o600, f"期望 0o600，实际 0o{mode:o}"


@pytest.mark.skipif(os.name != "posix", reason="Windows 不可靠地报告 group/other 位")
def test_existing_world_readable_key_logs_warning(tmp_path, monkeypatch, caplog):
    """已存在的 Fernet 密钥若权限过宽，应有 warning 日志提示运维。"""
    import logging

    key_file = tmp_path / ".fernet_key"
    key_file.write_bytes(b"existing-key-data")
    os.chmod(key_file, 0o644)
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))

    with caplog.at_level(logging.WARNING, logger="argus_py.core.crypto"):
        ensure_fernet_key()

    assert any("权限过宽" in rec.getMessage() for rec in caplog.records)
