"""测试 Fernet 密钥启动校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from argus_py.core.crypto import ensure_fernet_key
from argus_py.core.exceptions import ConfigError
from argus_py.infra.db import init_database


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

    ensure_fernet_key(db_path)
    assert key_file.exists()


def test_ensure_key_raises_when_db_has_encrypted_keys(tmp_path, monkeypatch):
    """key 不存在、DB 有加密记录 → 抛出 ConfigError。"""
    key_file = tmp_path / ".fernet_key"
    monkeypatch.setattr("argus_py.core.crypto.FERNET_KEY_FILE", str(key_file))
    monkeypatch.setattr("argus_py.core.crypto._has_encrypted_api_keys", lambda _: True)

    with pytest.raises(ConfigError, match="Fernet 密钥文件"):
        ensure_fernet_key(tmp_path / "irrelevant.db")

    assert not key_file.exists()
