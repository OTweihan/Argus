"""API Key 等敏感字段的加解密工具。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from argus_py.core.paths import FERNET_KEY_FILE

logger = logging.getLogger(__name__)

_SENTINEL = "f:"


class DBProbe(Protocol):
    """数据库探测端口 — 由上层注入，避免 ``core`` → ``infra`` 层倒挂。"""

    def has_encrypted_api_keys(self) -> bool:
        """检查数据库是否存在 Fernet 加密的 API Key（f: 前缀）。"""


def _load_or_create_key() -> bytes:
    """加载 Fernet 密钥，不存在时自动生成。"""
    key_path = Path(FERNET_KEY_FILE)
    if key_path.exists():
        return key_path.read_bytes()
    logger.warning(
        "Fernet 密钥文件 %s 不存在，正在自动生成。"
        " 已加密的 API key 将无法用新密钥解密，"
        "请备份此文件并妥善保管。",
        FERNET_KEY_FILE,
    )
    _generate_key_file()
    return key_path.read_bytes()


def _generate_key_file() -> None:
    """生成新 Fernet 密钥并写入文件。"""
    key = Fernet.generate_key()
    key_path = Path(FERNET_KEY_FILE)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    _restrict_key_permissions(key_path)


def _restrict_key_permissions(key_path: Path) -> None:
    """收紧密钥文件权限到仅 owner 可读写。

    POSIX 系统通过 ``chmod 0o600`` 阻止同机其他用户读取（私网部署常见多人
    SSH 同机器的运维风险）。Windows 上 ``os.chmod`` 仅影响只读位，等同 no-op；
    NTFS ACL 应由部署文档约束。
    """
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        logger.warning(
            "Fernet 密钥文件权限设置失败：%s",
            key_path,
            exc_info=True,
        )


def _warn_if_world_readable(key_path: Path) -> None:
    """POSIX 下若 key 文件 group/other 可读则告警，提示风险。"""
    if os.name != "posix":
        return
    try:
        mode = key_path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        logger.warning(
            "Fernet 密钥文件 %s 权限过宽 (0o%o)，建议执行 `chmod 600 %s`"
            "，避免同机其他用户读取并解密所有 API Key。",
            key_path,
            mode,
            key_path,
        )


def ensure_fernet_key(db_probe: DBProbe | None = None) -> None:
    """启动时校验 Fernet 密钥，避免运行时才发现 key 丢失。

    规则：
    - key 存在：正常返回（并对 POSIX 上权限过宽给出告警）
    - key 不存在且数据库无加密记录：自动生成新 key（权限收紧 0o600）
    - key 不存在但数据库有加密记录：抛出 ConfigError

    ``db_probe`` 由上层注入（如 ``infra.db._DefaultDBProbe``），
    避免 ``core`` 层直接依赖 ``infra`` 层。
    """
    key_path = Path(FERNET_KEY_FILE)
    if key_path.exists():
        _warn_if_world_readable(key_path)
        return

    if db_probe is not None and db_probe.has_encrypted_api_keys():
        from argus_py.core.exceptions import ConfigError

        raise ConfigError(
            f"Fernet 密钥文件 {FERNET_KEY_FILE} 不存在，"
            "但数据库中已有加密的模型 API Key。\n"
            "请恢复原 config/.fernet_key 后重启；如果无法恢复，请重新录入模型 API Key。\n"
            "为避免覆盖历史密钥，系统不会自动生成新的 Fernet key。"
        )

    logger.warning("Fernet 密钥文件 %s 不存在，正在自动生成。", FERNET_KEY_FILE)
    _generate_key_file()


def _get_fernet() -> Fernet:
    """获取 Fernet 实例。"""
    return Fernet(_load_or_create_key())


def encrypt_api_key(plain: str) -> str:
    """加密 API Key，返回带前缀的密文。"""
    if not plain:
        return ""
    token = _get_fernet().encrypt(plain.encode("utf-8"))
    return _SENTINEL + token.decode("utf-8")


def decrypt_api_key(maybe_encrypted: str) -> str:
    """解密 API Key，明文（无前缀）直接返回以兼容旧数据。"""
    if not maybe_encrypted:
        return ""
    if not maybe_encrypted.startswith(_SENTINEL):
        return maybe_encrypted
    token = maybe_encrypted[len(_SENTINEL) :].encode("utf-8")
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        raise ValueError(
            "API key 解密失败：Fernet 密钥与加密时使用的密钥不匹配。"
            f" 请检查 {FERNET_KEY_FILE} 是否被替换或丢失，"
            "恢复备份文件后可正常解密。"
        ) from None
