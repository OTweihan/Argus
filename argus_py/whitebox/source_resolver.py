"""源码解析器：处理 repo_url / 本地路径，准备分析输入。"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from argus_py.llm.url_guard import assert_llm_base_url_safe

logger = logging.getLogger(__name__)

# 允许的 Git 协议
_ALLOWED_SCHEMES = {"http", "https", "ssh", "git"}


class SourceResolutionError(Exception):
    """源码路径解析错误。"""


class SourceResolver:
    """解析 repo_url 或本地路径，返回可供分析的本地源码目录。

    行为
    ----
    - 如果提供的是本地路径，直接验证路径是否存在并返回。
    - 如果提供的是 repo_url，执行 Git 浅克隆到临时目录。
    - 私有仓库的凭据在日志中脱敏处理。
    """

    def __init__(self, work_dir: str | None = None) -> None:
        self._work_dir = Path(work_dir) if work_dir else Path("/tmp/sources")

    def resolve(self, repo_url: str, branch: str | None = None) -> str:
        """解析源码路径。

        Parameters
        ----------
        repo_url : str
            Git 仓库 URL 或本地文件系统路径。
        branch : str | None
            克隆的分支名，仅对 Git URL 有效。

        Returns
        -------
        str
            本地源码目录的绝对路径。

        Raises
        ------
        SourceResolutionError
            路径不存在、SSRF 校验失败或 Git 克隆失败。
        """
        if not repo_url:
            raise SourceResolutionError("repo_url 不能为空")

        # 本地路径：直接验证
        local_path = Path(repo_url)
        if local_path.exists():
            if not local_path.is_dir():
                raise SourceResolutionError(f"本地路径不是目录: {repo_url}")
            resolved = local_path.resolve()
            logger.info("使用本地源码路径: %s", resolved)
            return str(resolved)

        # Git URL：做 SSRF 校验后克隆
        parsed = urlparse(repo_url)
        if parsed.scheme not in _ALLOWED_SCHEMES and parsed.scheme:
            raise SourceResolutionError(f"不支持的协议: {parsed.scheme}，仅支持 {_ALLOWED_SCHEMES}")

        # SSRF 校验：复用 LLM URL guard
        try:
            assert_llm_base_url_safe(repo_url)
        except Exception as exc:
            raise SourceResolutionError(f"SSRF 校验失败: {exc}") from exc

        return self._clone(repo_url, branch)

    def resolve_path(self, source_path: str) -> str:
        """仅解析本地路径（不尝试 Git clone）。

        Parameters
        ----------
        source_path : str
            本地文件系统路径。

        Returns
        -------
        str
            规范化后的绝对路径。

        Raises
        ------
        SourceResolutionError
            路径不存在。
        """
        path = Path(source_path)
        if not path.exists():
            raise SourceResolutionError(f"路径不存在: {source_path}")
        if not path.is_dir():
            raise SourceResolutionError(f"路径不是目录: {source_path}")
        return str(path.resolve())

    def _clone(self, repo_url: str, branch: str | None = None) -> str:
        """执行 Git 浅克隆。

        Parameters
        ----------
        repo_url : str
            Git 仓库 URL。
        branch : str | None
            可选的分支名。

        Returns
        -------
        str
            克隆后的本地目录路径。
        """
        safe_url = _REDACT_CREDENTIALS.sub(r"\1***@", repo_url) if _REDACT_CREDENTIALS.search(repo_url) else repo_url
        target_dir = self._work_dir / _sanitize_dir_name(repo_url)
        if target_dir.exists():
            shutil.rmtree(target_dir)

        logger.info("克隆仓库: %s (branch=%s)", safe_url, branch or "default")

        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd.extend(["--branch", branch])
        cmd.extend([repo_url, str(target_dir)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                stderr = result.stderr[:500] if result.stderr else ""
                raise SourceResolutionError(
                    f"Git 克隆失败 (code={result.returncode}): {stderr}"
                )
            logger.info("仓库已克隆到: %s", target_dir)
            return str(target_dir.resolve())
        except subprocess.TimeoutExpired:
            raise SourceResolutionError(f"Git 克隆超时 (120s): {safe_url}")

    def cleanup(self) -> None:
        """清理临时工作目录。"""
        if self._work_dir.exists():
            shutil.rmtree(self._work_dir, ignore_errors=True)
            logger.info("已清理临时目录: %s", self._work_dir)


# 凭据脱敏正则：把 https://user:token@host → https://***@host
_REDACT_CREDENTIALS = re.compile(r"(https?://)[^@]+@")


def _sanitize_dir_name(url: str) -> str:
    """从 URL 生成安全的目录名。"""
    name = url.replace("://", "_").replace("/", "_").replace(":", "_")
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return name.strip("_") or "repo"
