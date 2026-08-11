"""源码解析器：处理 repo_url / 本地路径，准备分析输入。"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from argus_py.llm.url_guard import assert_llm_base_url_safe

logger = logging.getLogger(__name__)

# 允许的 Git 协议（与 config.py::validate_git_url 的入口白名单保持一致，不额外放行 git://）
_ALLOWED_SCHEMES = frozenset({"https", "http", "ssh"})

_HASH_CHUNK_SIZE = 1024 * 1024
_STALE_SNAPSHOT_SECONDS = 24 * 60 * 60
_SNAPSHOT_MARKER = ".argus_snapshot"

# 快照排除规则（O-07，保守、可配置）：只排除确定无关的 VCS、构建输出与工具缓存。
# 设计约束：
# - `.mvn`、`mvnw`/`mvnw.cmd`、`gradlew` 等 wrapper 配置**不排除**——可能参与构建流程；
# - 可能参与生成源码的目录（如 annotation processor 输出）未经验证不得排除，
#   因此这里只按目录名匹配确定无关项，不触碰 `.mvn`、`src` 等。
_DEFAULT_SNAPSHOT_EXCLUDE_DIRS = frozenset(
    {
        ".git",  # VCS
        ".svn",
        ".hg",
        "target",  # Maven 构建输出（含 generated-sources/classes，分析器不扫描）
        "build",  # Gradle 构建输出
        "out",  # IDE 编译输出
        ".gradle",  # Gradle 缓存
        "node_modules",  # 前端依赖
        ".idea",  # IDE 缓存
        ".vscode",
        ".settings",
        "__pycache__",  # Python 字节码
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",  # 通用工具缓存
        ".m2",  # 本地 Maven 仓库（通常不在仓库内）
        ".argus",  # 分析器自身 classpath 缓存
    }
)


@dataclass
class _SnapshotStats:
    """快照物化统计（O-07 指标）。复制与内容指纹在单次流式遍历中完成。"""

    file_count: int = 0
    copied_bytes: int = 0
    excluded_dir_count: int = 0
    copy_duration_ms: float = 0.0
    hash_duration_ms: float = 0.0
    content_sha256: str | None = None


@dataclass
class ResolvedSource:
    """源码解析结果（不可变快照标识）。

    所有来源都被物化到任务独立目录。Git 仓库保留 HEAD commit SHA，
    非 Git 目录使用完整快照内容的 SHA-256 作为快照标识。

    ``source_revision`` / ``snapshot_digest`` 是进入 Python→Java 契约的稳定
    revision（O-07）：Git 源用 commit SHA，本地源用快照内容 SHA-256。Java
    缓存键据此免去每次查找时全量读取源码树。
    """

    source_type: str  # "git" | "local"
    resolved_path: str  # 本地绝对路径
    requested_ref: str | None  # 用户输入的 branch/tag/commit 或 None
    resolved_commit_sha: str | None  # HEAD commit SHA 或非 Git 目录的内容哈希
    ref_type: str | None  # "branch" | "tag" | "commit" | "default"
    is_dirty: bool | None  # 原始 Git 工作区是否有未提交改动
    content_sha256: str | None = None
    managed_snapshot: bool = False
    # O-07：传给 Java 的稳定 revision / 快照内容摘要。
    # git 源 = commit SHA（snapshot_digest=None）；local 源 = 内容 SHA-256（两者相同）。
    source_revision: str | None = None
    snapshot_digest: str | None = None


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
        exclude_dirs: frozenset[str] | None = None,
    ) -> None:
        self._work_dir = (
            Path(work_dir) if work_dir else Path(tempfile.gettempdir(), "argus_sources")
        ).resolve()
        self._allowed_roots = allowed_roots or []
        # O-07：快照排除规则可配置；未指定时使用保守默认集。
        self._exclude_dirs = (
            frozenset(exclude_dirs) if exclude_dirs is not None else _DEFAULT_SNAPSHOT_EXCLUDE_DIRS
        )
        self._cleanup_stale_snapshots()
        # O-07 指标（快照物化统计），供 /metrics 汇总。SourceResolver 在
        # run_in_thread 线程池中被并发调用，累加需加锁防丢更新。
        self._stats_lock = threading.Lock()
        self._snapshot_count = 0
        self._snapshot_files_total = 0
        self._snapshot_bytes_total = 0
        self._snapshot_copy_ms_total = 0.0
        self._snapshot_hash_ms_total = 0.0
        self._snapshot_excluded_dirs_total = 0

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
            raise SourceResolutionError(
                f"不支持的协议: {parsed.scheme}，仅支持 {'/'.join(sorted(_ALLOWED_SCHEMES))} 或 scp 风格"
            )

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
            source_revision=sha,
            snapshot_digest=None,
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
        snapshot_dir, stats = self._copy_snapshot(
            resolved,
            snapshot_id or uuid.uuid4().hex[:12],
        )
        content_hash = stats.content_sha256
        logger.info(
            "本地源码已创建不可变快照 (hash=%s, files=%d, bytes=%d): %s -> %s",
            (content_hash or "")[:8],
            stats.file_count,
            stats.copied_bytes,
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
            # O-07：本地源以快照内容 SHA 同时充当 sourceRevision 与 snapshotDigest。
            source_revision=content_hash,
            snapshot_digest=content_hash,
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

    def _copy_snapshot(self, source: Path, snapshot_id: str) -> tuple[Path, _SnapshotStats]:
        """将本地源码物化为任务独立快照，复制与内容指纹单次流式遍历完成。

        Parameters
        ----------
        source : Path
            本地源码根目录。
        snapshot_id : str
            任务唯一标识，用于生成互不冲突的快照目录。

        Returns
        -------
        tuple[Path, _SnapshotStats]
            快照目录路径与物化统计（含内容 SHA-256）。
        """
        safe_id = _sanitize_dir_name(snapshot_id) or uuid.uuid4().hex[:12]
        snapshot_dir = self._work_dir / f"local_{_sanitize_dir_name(str(source))}__{safe_id}"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        self._validate_tree_symlinks(source)
        try:
            stats = self._materialize_snapshot(source, snapshot_dir)
            self._mark_snapshot(snapshot_dir)
        except (OSError, SourceResolutionError) as exc:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            raise SourceResolutionError(f"本地源码快照创建失败: {exc}") from exc
        self._record_snapshot_stats(stats)
        return snapshot_dir.resolve(), stats

    def _materialize_snapshot(self, source: Path, dest: Path) -> _SnapshotStats:
        """单次流式遍历：把源码复制到 ``dest`` 并同时计算内容 SHA-256。

        哈希格式与旧 ``_compute_dir_hash`` 保持一致：每个被复制文件先写入
        （8 字节大端长度 + 相对 POSIX 路径），再写入文件内容，按相对路径排序
        保证确定性。排除规则作用于目录名（任意深度），排除目录既不复制也不
        参与哈希。复制与哈希共享同一次文件读取。
        """
        stats = _SnapshotStats()
        hasher = hashlib.sha256()
        copy_start = time.perf_counter()
        # 空目录（或全部文件被排除）时也必须物化出一个目录，供 _mark_snapshot 落标。
        dest.mkdir(parents=True, exist_ok=True)

        # 先收集 (源文件, 相对路径) 并按相对路径排序，保证哈希输入确定。
        # 跟随目录符号链接（与旧 copytree 语义一致），但用已访问的真实路径
        # 防环；排除规则作用于目录名（任意深度）。
        entries: list[tuple[Path, Path]] = []
        excluded_dirs = 0
        visited_dirs: set[str] = set()
        stack: list[tuple[Path, Path]] = [(source, Path())]
        while stack:
            cur_dir, rel_dir = stack.pop()
            try:
                real = cur_dir.resolve(strict=True)
            except OSError:
                continue
            if str(real) in visited_dirs:
                continue
            visited_dirs.add(str(real))
            try:
                children = sorted(cur_dir.iterdir(), key=lambda p: p.name)
            except OSError as exc:
                raise SourceResolutionError(f"无法读取快照源目录: {cur_dir}") from exc
            subdirs: list[tuple[Path, Path]] = []
            for child in children:
                name = child.name
                if name == _SNAPSHOT_MARKER:
                    continue
                if child.is_dir():
                    if name in self._exclude_dirs:
                        excluded_dirs += 1
                    else:
                        subdirs.append((child, rel_dir / name))
                elif child.is_file():
                    # 文件符号链接兜底逃逸检查：`_validate_tree_symlinks` 的 rglob
                    # 不深入符号链接目录，物化会跟随进入（与旧 copytree 语义一致），
                    # 因此目录链接内部的文件链接必须在此处再次校验，防止源外内容
                    # 被复制进共享快照。
                    if child.is_symlink():
                        try:
                            target = child.resolve(strict=True)
                            target.relative_to(source)
                        except (OSError, ValueError) as exc:
                            raise SourceResolutionError(
                                f"源码目录包含越界或无效符号链接: {child}"
                            ) from exc
                    entries.append((child, rel_dir / name))
            for d in reversed(subdirs):
                stack.append(d)
        entries.sort(key=lambda pair: pair[1].as_posix())

        for src_file, dest_rel in entries:
            dst_file = dest / dest_rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            rel_bytes = dest_rel.as_posix().encode("utf-8")
            hasher.update(len(rel_bytes).to_bytes(8, "big"))
            hasher.update(rel_bytes)
            copied = 0
            try:
                with src_file.open("rb") as reader, dst_file.open("wb") as writer:
                    while chunk := reader.read(_HASH_CHUNK_SIZE):
                        writer.write(chunk)
                        # 指纹耗时单独累计：只计 SHA-256 update 的 CPU 时间，
                        # 文件 I/O 归入复制耗时。
                        tick = time.perf_counter()
                        hasher.update(chunk)
                        stats.hash_duration_ms += (time.perf_counter() - tick) * 1000.0
                        copied += len(chunk)
            except OSError as exc:
                raise SourceResolutionError(f"无法复制或读取快照文件: {src_file}") from exc
            stats.file_count += 1
            stats.copied_bytes += copied

        stats.copy_duration_ms = (time.perf_counter() - copy_start) * 1000.0
        stats.excluded_dir_count = excluded_dirs
        stats.content_sha256 = hasher.hexdigest()
        return stats

    def _record_snapshot_stats(self, stats: _SnapshotStats) -> None:
        """累加快照物化指标（O-07）。多任务并发物化时加锁防丢更新。"""
        with self._stats_lock:
            self._snapshot_count += 1
            self._snapshot_files_total += stats.file_count
            self._snapshot_bytes_total += stats.copied_bytes
            self._snapshot_copy_ms_total += stats.copy_duration_ms
            self._snapshot_hash_ms_total += stats.hash_duration_ms
            self._snapshot_excluded_dirs_total += stats.excluded_dir_count

    def metrics(self) -> dict[str, int | float]:
        """快照物化指标（O-07），供 /metrics 汇总。

        复制与指纹在单次流式遍历中合并完成，因此统一报告物化耗时与指纹
        CPU 耗时。用这些数据决定是否继续引入增量 per-file digest。
        """
        with self._stats_lock:
            return {
                "snapshot_count": self._snapshot_count,
                "snapshot_files_total": self._snapshot_files_total,
                "snapshot_bytes_total": self._snapshot_bytes_total,
                "snapshot_copy_ms_total": round(self._snapshot_copy_ms_total, 3),
                "snapshot_hash_ms_total": round(self._snapshot_hash_ms_total, 3),
                "snapshot_excluded_dirs_total": self._snapshot_excluded_dirs_total,
            }

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
