"""源码解析器：处理 repo_url / 本地路径，准备分析输入。"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from argus_py.llm.url_guard import assert_llm_base_url_safe

logger = logging.getLogger(__name__)

# 允许的 Git 协议
_ALLOWED_SCHEMES = {"http", "https", "ssh", "git"}


@dataclass
class ResolvedSource:
    """源码解析结果（不可变快照标识）。"""

    source_type: str  # "git" | "local"
    resolved_path: str  # 本地绝对路径
    requested_ref: str | None  # 用户输入的 branch/tag/commit 或 None
    resolved_commit_sha: str | None  # HEAD commit SHA（本地非 Git 目录为 None）
    ref_type: str | None  # "branch" | "tag" | "commit" | "default"
    is_dirty: bool | None  # Git 仓库工作时脏状态（非 Git 为 None）


class SourceResolutionError(Exception):
    """源码路径解析错误。"""


class SourceResolver:
    """解析 repo_url 或本地路径，返回可供分析的本地源码目录。

    行为
    ----
    - 如果提供的是本地路径，直接验证路径是否存在并返回。
    - 如果提供的是 repo_url，执行 Git 浅克隆到临时目录。
    - 私有仓库的凭据在日志中脱敏处理。
    - allowed_roots 校验源码路径必须在允许的根目录内。
    """

    def __init__(
        self,
        work_dir: str | None = None,
        allowed_roots: list[Path] | None = None,
    ) -> None:
        self._work_dir = (
            Path(work_dir) if work_dir else Path(tempfile.gettempdir(), "argus_sources")
        )
        self._allowed_roots = allowed_roots or []

    def resolve(self, repo_url: str, ref: str | None = None) -> ResolvedSource:
        """解析 Git 仓库源码路径。

        Parameters
        ----------
        repo_url : str
            Git 仓库 URL 或本地文件系统路径。
            不允许 file://、ext:: 或内嵌凭据。
        ref : str | None
            分支名 / tag / commit SHA。

        Returns
        -------
        ResolvedSource
            包含 resolved_path、commit_sha 和元数据的解析结果。

        Raises
        ------
        SourceResolutionError
            SSRF 校验、Git 克隆或 commit SHA 获取失败。
        """
        if not repo_url:
            raise SourceResolutionError("repo_url 不能为空")

        # 本地路径：直接委托给 resolve_path
        local_path = Path(repo_url)
        if local_path.exists():
            if not local_path.is_dir():
                raise SourceResolutionError(f"本地路径不是目录: {repo_url}")
            return self.resolve_path(repo_url)

        # Git URL：做 SSRF 校验后克隆
        parsed = urlparse(repo_url)
        # 处理 scp 风格: git@host:org/repo.git
        if "://" not in repo_url and ":" in repo_url and repo_url.startswith("git@"):
            # SCP 风格 — 允许
            pass
        elif parsed.scheme not in _ALLOWED_SCHEMES and parsed.scheme:
            raise SourceResolutionError(f"不支持的协议: {parsed.scheme}，仅支持 {_ALLOWED_SCHEMES}")

        # SSRF 校验：复用 LLM URL guard
        try:
            assert_llm_base_url_safe(repo_url)
        except Exception as exc:
            raise SourceResolutionError(f"SSRF 校验失败: {exc}") from exc

        resolved_path = self._clone(repo_url, ref)

        # 获取 HEAD commit SHA（必须成功）
        sha = self._get_head_commit(Path(resolved_path))
        if sha is None:
            raise SourceResolutionError(
                "无法获取 Git HEAD commit SHA。请确认仓库有 commit 记录且 git 可用。"
            )

        is_dirty = self._get_dirty_status(Path(resolved_path))
        ref_type = self._classify_ref(ref)

        return ResolvedSource(
            source_type="git",
            resolved_path=resolved_path,
            requested_ref=ref,
            resolved_commit_sha=sha,
            ref_type=ref_type,
            is_dirty=is_dirty,
        )

    def resolve_path(self, source_path: str) -> ResolvedSource:
        """仅解析本地路径（不尝试 Git clone）。

        Parameters
        ----------
        source_path : str
            本地文件系统路径。

        Returns
        -------
        ResolvedSource
            包含 resolved_path、commit_sha（如果目录是 Git 仓库）的解析结果。

        Raises
        ------
        SourceResolutionError
            路径不存在或不在允许范围内。
        """
        path = Path(source_path)
        if not path.exists():
            raise SourceResolutionError(f"路径不存在: {source_path}")
        if not path.is_dir():
            raise SourceResolutionError(f"路径不是目录: {source_path}")

        self._validate_within_allowed_roots(path)

        # 软链接逃逸检测
        resolved = path.resolve(strict=True)
        self._validate_within_allowed_roots(resolved)

        # 检查是否为 Git 仓库
        sha = self._get_head_commit(resolved)
        is_dirty = self._get_dirty_status(resolved) if sha else None

        return ResolvedSource(
            source_type="local",
            resolved_path=str(resolved),
            requested_ref=None,
            resolved_commit_sha=sha,
            ref_type=None,
            is_dirty=is_dirty,
        )

    def _clone(self, repo_url: str, ref: str | None = None) -> str:
        """执行 Git 浅克隆。

        Parameters
        ----------
        repo_url : str
            Git 仓库 URL。
        ref : str | None
            可选的 branch/tag/commit。

        Returns
        -------
        str
            克隆后的本地目录路径。
        """
        safe_url = (
            _REDACT_CREDENTIALS.sub(r"\1***@", repo_url)
            if _REDACT_CREDENTIALS.search(repo_url)
            else repo_url
        )
        target_dir = self._work_dir / _sanitize_dir_name(repo_url)
        if target_dir.exists():
            shutil.rmtree(target_dir)

        logger.info("克隆仓库: %s (ref=%s)", safe_url, ref or "default")

        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd.extend(["--branch", ref])
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
                raise SourceResolutionError(f"Git 克隆失败 (code={result.returncode}): {stderr}")
            logger.info("仓库已克隆到: %s", target_dir)
            return str(target_dir.resolve())
        except subprocess.TimeoutExpired:
            raise SourceResolutionError(f"Git 克隆超时 (120s): {safe_url}")

    def _get_head_commit(self, repo_dir: Path) -> str | None:
        """获取 Git 仓库 HEAD commit SHA。"""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    def _get_dirty_status(self, repo_dir: Path) -> bool | None:
        """检查 Git 仓库是否有未提交的改动。"""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_dir), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    @staticmethod
    def _classify_ref(ref: str | None) -> str | None:
        """分类用户提供的 ref：branch / tag / commit / default。"""
        if ref is None:
            return "default"
        # 全 SHA (40 hex chars) → commit
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            return "commit"
        # 短 SHA (7-39 hex chars) → commit
        if re.fullmatch(r"[0-9a-f]{7,39}", ref):
            return "commit"
        # 其他 → 先当 branch（tag 需要在 clone 后判断）
        return "branch"

    def _validate_within_allowed_roots(self, path: Path) -> None:
        """校验 path 是否在允许的源码根目录内。"""
        if not self._allowed_roots:
            return
        resolved = path.resolve(strict=True) if path.exists() else path.resolve()
        for root in self._allowed_roots:
            root_resolved = root.resolve(strict=True) if root.exists() else root.resolve()
            try:
                resolved.relative_to(root_resolved)
                return
            except ValueError:
                continue
        raise SourceResolutionError(
            f"源码路径 {path} 不在允许的根目录范围内。"
            f"允许的根目录: {[str(r) for r in self._allowed_roots]}"
        )

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
