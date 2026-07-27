"""源码解析器：处理 repo_url / 本地路径，准备分析输入。"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from argus_py.llm.url_guard import assert_llm_base_url_safe

logger = logging.getLogger(__name__)

# 允许的 Git 协议
_ALLOWED_SCHEMES = {"http", "https", "ssh", "git"}

_HASH_CHUNK_SIZE = 1024 * 1024
_STALE_SNAPSHOT_SECONDS = 24 * 60 * 60
_SNAPSHOT_MARKER = ".argus_snapshot"


@dataclass
class ResolvedSource:
    """源码解析结果（不可变快照标识）。

    所有来源都被物化到任务独立目录。Git 仓库保留 HEAD commit SHA，
    非 Git 目录使用完整快照内容的 SHA-256 作为快照标识。
    """

    source_type: str  # "git" | "local"
    resolved_path: str  # 本地绝对路径
    requested_ref: str | None  # 用户输入的 branch/tag/commit 或 None
    resolved_commit_sha: str | None  # HEAD commit SHA 或非 Git 目录的内容哈希
    ref_type: str | None  # "branch" | "tag" | "commit" | "default"
    is_dirty: bool | None  # 原始 Git 工作区是否有未提交改动
    content_sha256: str | None = None
    managed_snapshot: bool = False


class SourceResolutionError(Exception):
    """源码路径解析错误。"""


class SourceResolver:
    """解析 repo_url 或本地路径，返回可供分析的不可变源码目录。

    行为
    ----
    - 远程仓库 (repo_url)：Git 浅克隆到临时快照目录。
    - 本地目录：拷贝到任务独立目录，再计算完整内容哈希。
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
        ).resolve()
        self._allowed_roots = allowed_roots or []
        self._cleanup_stale_snapshots()

    def resolve(
        self, repo_url: str, ref: str | None = None, *, clone_id: str | None = None
    ) -> ResolvedSource:
        """解析 Git 仓库源码路径。

        Parameters
        ----------
        repo_url : str
            Git 仓库 URL 或本地文件系统路径。
            不允许 file://、ext:: 或内嵌凭据。
        ref : str | None
            分支名 / tag / commit SHA。
        clone_id : str | None
            调用方提供的唯一标识（如 task_id），用于生成互不冲突的克隆目录。
            未提供时自动生成 UUID。

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
        self._cleanup_stale_snapshots()

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

        resolved_path = self._clone(repo_url, ref, clone_id or uuid.uuid4().hex[:12])

        # 获取 HEAD commit SHA（必须成功）
        sha = self._get_head_commit(Path(resolved_path))
        if sha is None:
            raise SourceResolutionError(
                "无法获取 Git HEAD commit SHA。请确认仓库有 commit 记录且 git 可用。"
            )

        ref_type = self._classify_ref(ref)
        # 克隆后重新确认 ref_type：非 commit 的 ref 可能是 branch 或 tag
        if ref_type == "ref" and ref is not None:
            ref_type = "tag" if self._is_tag(Path(resolved_path), ref) else "branch"

        # Git 仓库以 commit SHA 为精确内容标识，无需全量目录哈希
        return ResolvedSource(
            source_type="git",
            resolved_path=resolved_path,
            requested_ref=ref,
            resolved_commit_sha=sha,
            ref_type=ref_type,
            is_dirty=False,  # 浅克隆始终干净
            content_sha256=None,
            managed_snapshot=True,
        )

    def resolve_path(self, source_path: str, *, snapshot_id: str | None = None) -> ResolvedSource:
        """解析本地路径，创建不可变快照用于分析。

        Git 和非 Git 目录都会先拷贝到任务独立目录，
        Java 只分析该不可变快照。

        Parameters
        ----------
        source_path : str
            本地文件系统路径。

        Returns
        -------
        ResolvedSource
            包含 resolved_path、commit_sha 的解析结果。
            返回任务独立快照路径和快照标识。

        Raises
        ------
        SourceResolutionError
            路径不存在、不在允许范围内，或快照创建失败。
        """
        path = Path(source_path)
        self._cleanup_stale_snapshots()
        if not path.exists():
            raise SourceResolutionError(f"路径不存在: {source_path}")
        if not path.is_dir():
            raise SourceResolutionError(f"路径不是目录: {source_path}")

        self._validate_within_allowed_roots(path)

        # 软链接逃逸检测
        resolved = path.resolve(strict=True)
        self._validate_within_allowed_roots(resolved)

        try:
            self._work_dir.relative_to(resolved)
        except ValueError:
            pass
        else:
            raise SourceResolutionError("快照工作目录不能位于源码目录内")

        # 先记录原始 Git 状态，再物化不可变快照
        sha = self._get_head_commit(resolved)
        is_dirty = self._get_dirty_status(resolved) if sha else None
        snapshot_dir = self._copy_snapshot(
            resolved,
            snapshot_id or uuid.uuid4().hex[:12],
        )
        content_hash = self._compute_dir_hash(snapshot_dir)
        logger.info(
            "本地源码已创建不可变快照 (hash=%s): %s -> %s",
            content_hash[:8],
            resolved,
            snapshot_dir,
        )
        return ResolvedSource(
            source_type="local",
            resolved_path=str(snapshot_dir),
            requested_ref=None,
            resolved_commit_sha=sha or content_hash,
            ref_type="commit" if sha else None,
            is_dirty=is_dirty,
            content_sha256=content_hash,
            managed_snapshot=True,
        )

    def _clone(self, repo_url: str, ref: str | None = None, clone_id: str = "") -> str:
        """执行 Git 浅克隆。

        Parameters
        ----------
        repo_url : str
            Git 仓库 URL。
        ref : str | None
            可选的 branch/tag/commit。
        clone_id : str
            调用方提供的唯一标识，用于生成互不冲突的克隆目录。

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
        # 并发隔离：clone_id 确保同一仓库的并发任务使用不同目录
        safe_clone_id = _sanitize_dir_name(clone_id) or uuid.uuid4().hex[:12]
        target_dir = self._work_dir / f"{_sanitize_dir_name(repo_url)}__{safe_clone_id}"
        if target_dir.exists():
            shutil.rmtree(target_dir)

        logger.info("克隆仓库: %s (ref=%s)", safe_url, ref or "default")

        ref_type = self._classify_ref(ref)
        commands: list[list[str]]
        if ref_type == "commit":
            assert ref is not None
            commands = [
                ["git", "init", str(target_dir)],
                ["git", "-C", str(target_dir), "remote", "add", "origin", repo_url],
                ["git", "-C", str(target_dir), "fetch", "--depth", "1", "origin", ref],
                ["git", "-C", str(target_dir), "checkout", "--detach", "FETCH_HEAD"],
            ]
        else:
            command = ["git", "clone", "--depth", "1"]
            if ref:
                command.extend(["--branch", ref])
            command.extend([repo_url, str(target_dir)])
            commands = [command]

        try:
            for command in commands:
                result = subprocess.run(
                    command,
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
            self._mark_snapshot(target_dir)
            return str(target_dir.resolve())
        except subprocess.TimeoutExpired:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise SourceResolutionError(f"Git 克隆超时 (120s): {safe_url}")
        except SourceResolutionError:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    def _copy_snapshot(self, source: Path, snapshot_id: str) -> Path:
        """将本地源码物化为任务独立快照。"""
        safe_id = _sanitize_dir_name(snapshot_id) or uuid.uuid4().hex[:12]
        snapshot_dir = self._work_dir / f"local_{_sanitize_dir_name(str(source))}__{safe_id}"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        self._validate_tree_symlinks(source)
        try:
            shutil.copytree(
                source,
                snapshot_dir,
                symlinks=False,
                ignore=shutil.ignore_patterns(".git"),
            )
            self._mark_snapshot(snapshot_dir)
        except (OSError, SourceResolutionError) as exc:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            raise SourceResolutionError(f"本地源码快照创建失败: {exc}") from exc
        return snapshot_dir.resolve()

    @staticmethod
    def _mark_snapshot(snapshot_dir: Path) -> None:
        """写入管理标记，供安全释放和 TTL 清理识别。"""
        try:
            (snapshot_dir / _SNAPSHOT_MARKER).write_text(
                "argus-whitebox-snapshot\n", encoding="utf-8"
            )
        except OSError as exc:
            raise SourceResolutionError(f"无法写入快照管理标记: {snapshot_dir}") from exc

    @staticmethod
    def _validate_tree_symlinks(source: Path) -> None:
        """拒绝指向源码根目录之外的符号链接。"""
        for entry in source.rglob("*"):
            if not entry.is_symlink():
                continue
            try:
                target = entry.resolve(strict=True)
                target.relative_to(source)
            except (OSError, ValueError) as exc:
                raise SourceResolutionError(f"源码目录包含越界或无效符号链接: {entry}") from exc

    def _compute_dir_hash(self, dir_path: Path) -> str:
        """按相对路径排序计算快照的完整 SHA-256。"""
        hasher = hashlib.sha256()
        files = [
            f
            for f in dir_path.rglob("*")
            if f.is_file()
            and f.name != _SNAPSHOT_MARKER
            and ".git" not in f.relative_to(dir_path).parts
        ]
        files.sort(key=lambda p: p.relative_to(dir_path))
        for f in files:
            rel = f.relative_to(dir_path).as_posix().encode("utf-8")
            hasher.update(len(rel).to_bytes(8, "big"))
            hasher.update(rel)
            try:
                with f.open("rb") as stream:
                    while chunk := stream.read(_HASH_CHUNK_SIZE):
                        hasher.update(chunk)
            except OSError as exc:
                raise SourceResolutionError(f"无法读取快照文件: {f}") from exc
        return hasher.hexdigest()

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
        """检查 Git 仓库工作区是否有未提交改动。"""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_dir), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip()) if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError):
            return None

    @staticmethod
    def _classify_ref(ref: str | None) -> str | None:
        """分类用户提供的 ref：commit / ref / default。

        注意：非 hex 字符串无法在克隆前区分 branch 和 tag；
        此处统一标记为 "ref"，克隆后由 _is_tag 重新确认。
        """
        if ref is None:
            return "default"
        # 全 SHA (40 hex chars) → commit
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            return "commit"
        # 短 SHA (7-39 hex chars) → commit
        if re.fullmatch(r"[0-9a-f]{7,39}", ref):
            return "commit"
        # 其他 → 先标记为 "ref"（分支/标签由克隆后检测）
        return "ref"

    @staticmethod
    def _is_tag(repo_dir: Path, ref: str) -> bool:
        """检查 ref 是否为 Git tag。"""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_dir), "show-ref", "--tags", "--verify", f"refs/tags/{ref}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

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

    def release(self, resolved: ResolvedSource) -> None:
        """只清理当前任务管理的快照目录。"""
        if not resolved.managed_snapshot:
            return
        target = Path(resolved.resolved_path).resolve()
        try:
            target.relative_to(self._work_dir)
        except ValueError as exc:
            raise SourceResolutionError(f"拒绝清理工作目录之外的路径: {target}") from exc
        if target == self._work_dir:
            raise SourceResolutionError("拒绝清理快照工作目录根路径")
        if not (target / _SNAPSHOT_MARKER).is_file():
            raise SourceResolutionError(f"拒绝清理未受 Argus 管理的目录: {target}")
        shutil.rmtree(target, ignore_errors=True)

    def _cleanup_stale_snapshots(self) -> None:
        """清理超过 24 小时的遗留快照，兼容中断后远端仍在运行的作业。

        依赖文件系统 mtime 判断快照年龄——在容器重启等场景下 mtime
        可能被保留或重置，因此 TTL 不提供精确保证（误差在数小时量级），
        仅作为兜底回收机制。
        """
        if not self._work_dir.exists():
            return
        cutoff = time.time() - _STALE_SNAPSHOT_SECONDS
        for child in self._work_dir.iterdir():
            try:
                if (
                    child.is_dir()
                    and (child / _SNAPSHOT_MARKER).is_file()
                    and child.stat().st_mtime < cutoff
                ):
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                logger.warning("清理遗留快照失败: %s", child, exc_info=True)

    def cleanup(self) -> None:
        """清理整个临时工作目录（仅用于测试/进程整体回收）。"""
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
