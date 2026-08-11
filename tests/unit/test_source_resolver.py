"""SourceResolver 单元测试。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from argus_py.whitebox.source_resolver import SourceResolutionError, SourceResolver


def _resolver(tmp_path: Path) -> SourceResolver:
    return SourceResolver(work_dir=str(tmp_path / "snapshots"))


def test_resolve_path_creates_independent_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "demo.txt").write_text("before", encoding="utf-8")

    resolver = _resolver(tmp_path)
    result = resolver.resolve_path(str(source), snapshot_id="task-1")

    snapshot = Path(result.resolved_path)
    assert snapshot != source.resolve()
    assert (snapshot / "demo.txt").read_text(encoding="utf-8") == "before"
    assert result.managed_snapshot is True
    assert result.content_sha256
    assert result.resolved_commit_sha == result.content_sha256

    (source / "demo.txt").write_text("after", encoding="utf-8")
    assert (snapshot / "demo.txt").read_text(encoding="utf-8") == "before"


def test_release_only_removes_current_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "demo.txt").write_text("hello", encoding="utf-8")
    resolver = _resolver(tmp_path)
    first = resolver.resolve_path(str(source), snapshot_id="task-1")
    second = resolver.resolve_path(str(source), snapshot_id="task-2")

    resolver.release(first)

    assert not Path(first.resolved_path).exists()
    assert Path(second.resolved_path).is_dir()
    assert source.is_dir()


def test_full_hash_changes_after_content_beyond_64kb(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = bytearray(b"a" * (70 * 1024))
    (source / "large.bin").write_bytes(payload)
    resolver = _resolver(tmp_path)
    first = resolver.resolve_path(str(source), snapshot_id="task-1")

    payload[-1] = ord("b")
    (source / "large.bin").write_bytes(payload)
    second = resolver.resolve_path(str(source), snapshot_id="task-2")

    assert first.content_sha256 != second.content_sha256


def test_local_git_snapshot_preserves_dirty_audit_state(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "argus@example.test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Argus Test"], check=True)
    tracked = source / "tracked.txt"
    tracked.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-m", "initial"], check=True)
    tracked.write_text("dirty", encoding="utf-8")

    result = _resolver(tmp_path).resolve_path(str(source), snapshot_id="task-git")

    assert result.is_dirty is True
    assert result.resolved_commit_sha
    assert result.content_sha256
    assert (Path(result.resolved_path) / "tracked.txt").read_text(encoding="utf-8") == "dirty"
    assert not (Path(result.resolved_path) / ".git").exists()


def test_resolve_path_rejects_work_dir_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    resolver = SourceResolver(work_dir=str(source / "snapshots"))
    with pytest.raises(SourceResolutionError, match="不能位于源码目录内"):
        resolver.resolve_path(str(source))


def test_resolve_path_non_existent(tmp_path: Path) -> None:
    with pytest.raises(SourceResolutionError, match="路径不存在"):
        _resolver(tmp_path).resolve_path(str(tmp_path / "does-not-exist"))


def test_resolve_path_file_instead_of_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "test.txt"
    file_path.write_text("hello", encoding="utf-8")
    with pytest.raises(SourceResolutionError, match="不是目录"):
        _resolver(tmp_path).resolve_path(str(file_path))


def test_resolve_local_path(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    result = _resolver(tmp_path).resolve(str(source))
    assert Path(result.resolved_path).is_dir()
    assert Path(result.resolved_path) != source.resolve()


def test_resolve_empty_url_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceResolutionError, match="repo_url 不能为空"):
        _resolver(tmp_path).resolve("")


def test_resolve_unsupported_scheme(tmp_path: Path) -> None:
    with pytest.raises(SourceResolutionError, match="不支持的协议"):
        _resolver(tmp_path).resolve("ftp://example.com/repo.git")


def test_resolve_git_scheme_rejected(tmp_path: Path) -> None:
    """git:// 协议与 config.py::validate_git_url 入口白名单保持一致，解析器同样拒绝。"""
    with pytest.raises(SourceResolutionError, match="不支持的协议"):
        _resolver(tmp_path).resolve("git://example.com/repo.git")


def test_resolve_ssrf_rejection(tmp_path: Path) -> None:
    with pytest.raises(SourceResolutionError, match="SSRF"):
        _resolver(tmp_path).resolve("http://169.254.169.254/latest/meta-data/")


def test_clone_commit_ref_uses_fetch_and_detached_checkout(tmp_path: Path, monkeypatch) -> None:
    resolver = _resolver(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["git", "init"]:
            Path(command[-1]).mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    commit = "a" * 40

    resolver._clone("https://example.com/org/repo.git", commit, "task-1")

    assert commands[0][:2] == ["git", "init"]
    assert commands[2][-3:] == ["1", "origin", commit]
    assert commands[3][-2:] == ["--detach", "FETCH_HEAD"]


def test_cleanup_idempotent(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path)
    resolver.cleanup()
    resolver.cleanup()


def test_sanitize_dir_name() -> None:
    from argus_py.whitebox.source_resolver import _sanitize_dir_name

    assert (
        _sanitize_dir_name("https://github.com/user/repo.git") == "https_github_com_user_repo_git"
    )
    assert _sanitize_dir_name("git@github.com:user/repo.git") == "git_github_com_user_repo_git"
    assert _sanitize_dir_name("/tmp/path") == "tmp_path"
    assert ".." not in _sanitize_dir_name("../evil-path")


def test_classify_ref_returns_ref_for_non_hex(tmp_path: Path) -> None:
    """非 hex 字符串统一返回 'ref'，克隆后由 _is_tag 重新确认。"""
    resolver = _resolver(tmp_path)
    assert resolver._classify_ref(None) == "default"
    assert resolver._classify_ref("a" * 40) == "commit"
    assert resolver._classify_ref("abc1234") == "commit"
    assert resolver._classify_ref("main") == "ref"
    assert resolver._classify_ref("v1.0.0") == "ref"
    assert resolver._classify_ref("feature/login") == "ref"


def test_is_tag_true_when_tag_exists(tmp_path: Path) -> None:
    """已有 tag 的仓库中 _is_tag 返回 True。"""
    from argus_py.whitebox.source_resolver import SourceResolver

    repo = tmp_path / "tagged"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "argus@example.test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Argus Test"], check=True)
    (repo / "f.txt").write_text("tagged", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "tag", "v1.0"],
        check=True,
        capture_output=True,
    )

    assert SourceResolver._is_tag(repo, "v1.0") is True
    assert SourceResolver._is_tag(repo, "v9.9") is False


def test_release_rejects_path_outside_work_dir(tmp_path: Path) -> None:
    """release() 拒绝清理工作目录之外的路径。"""
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolutionError

    source = tmp_path / "src"
    source.mkdir()
    (source / "f.txt").write_text("x", encoding="utf-8")
    resolver = _resolver(tmp_path)

    # 构造一个指向工作目录外的 ResolvedSource
    bad = ResolvedSource(
        source_type="local",
        resolved_path=str(tmp_path / "outside"),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
        managed_snapshot=True,
    )

    with pytest.raises(SourceResolutionError, match="拒绝清理工作目录之外的路径"):
        resolver.release(bad)


def test_release_rejects_root_work_dir(tmp_path: Path) -> None:
    """release() 拒绝清理快照工作目录根路径自身。"""
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolutionError

    resolver = _resolver(tmp_path)
    bad = ResolvedSource(
        source_type="local",
        resolved_path=str(resolver._work_dir),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
        managed_snapshot=True,
    )

    with pytest.raises(SourceResolutionError, match="拒绝清理快照工作目录根路径"):
        resolver.release(bad)


def test_release_rejects_directory_without_marker(tmp_path: Path) -> None:
    """release() 拒绝清理未受 Argus 管理的目录。"""
    from argus_py.whitebox.source_resolver import ResolvedSource, SourceResolutionError

    resolver = _resolver(tmp_path)
    resolver._work_dir.mkdir(parents=True, exist_ok=True)
    unmanaged = resolver._work_dir / "not-managed"
    unmanaged.mkdir()

    bad = ResolvedSource(
        source_type="local",
        resolved_path=str(unmanaged),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
        managed_snapshot=True,
    )

    with pytest.raises(SourceResolutionError, match="拒绝清理未受 Argus 管理的目录"):
        resolver.release(bad)


def test_release_skips_non_managed_source(tmp_path: Path) -> None:
    """非管理快照直接跳过不抛异常。"""
    from argus_py.whitebox.source_resolver import ResolvedSource

    source = tmp_path / "src"
    source.mkdir()
    result = ResolvedSource(
        source_type="local",
        resolved_path=str(source),
        requested_ref=None,
        resolved_commit_sha=None,
        ref_type=None,
        is_dirty=None,
        managed_snapshot=False,
    )

    _resolver(tmp_path).release(result)
    # 不抛异常即通过


def test_cleanup_stale_snapshots_removes_expired(tmp_path: Path) -> None:
    """TTL 清理移除超过 24h 的快照。"""
    import time

    from argus_py.whitebox.source_resolver import _SNAPSHOT_MARKER

    resolver = _resolver(tmp_path)
    resolver._work_dir.mkdir(parents=True, exist_ok=True)
    stale = resolver._work_dir / "stale_dir"
    stale.mkdir()
    (stale / _SNAPSHOT_MARKER).write_text("argus-whitebox-snapshot\n", encoding="utf-8")

    # 设置为 25 小时前
    old_time = time.time() - 25 * 3600
    os.utime(stale, (old_time, old_time))

    resolver._cleanup_stale_snapshots()
    assert not stale.exists()


def test_cleanup_stale_snapshots_keeps_fresh(tmp_path: Path) -> None:
    """TTL 清理保留 24h 内的快照。"""
    from argus_py.whitebox.source_resolver import _SNAPSHOT_MARKER

    resolver = _resolver(tmp_path)
    resolver._work_dir.mkdir(parents=True, exist_ok=True)
    fresh = resolver._work_dir / "fresh_dir"
    fresh.mkdir()
    (fresh / _SNAPSHOT_MARKER).write_text("argus-whitebox-snapshot\n", encoding="utf-8")

    resolver._cleanup_stale_snapshots()
    assert fresh.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="Windows 创建符号链接需要管理员权限")
def test_symlink_escaping_source_dir_is_rejected(tmp_path: Path) -> None:
    """符号链接指向源码根目录之外的路径时被拒绝。"""
    resolver = _resolver(tmp_path)
    source = tmp_path / "leaky"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_link = source / "escape"
    outside_link.symlink_to(outside)

    with pytest.raises(SourceResolutionError, match="越界或无效符号链接"):
        resolver._validate_tree_symlinks(source)


@pytest.mark.skipif(os.name == "nt", reason="Windows 创建符号链接需要管理员权限")
def test_snapshot_follows_dir_symlink_without_cycle(tmp_path: Path) -> None:
    """O-07：目录符号链接被跟随（与旧 copytree 语义一致），且循环链接不死循环。"""
    source = tmp_path / "src"
    source.mkdir()
    (source / "Main.java").write_text("class Main {}", encoding="utf-8")
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "Shared.java").write_text("class Shared {}", encoding="utf-8")
    (source / "link-to-real").symlink_to(real_dir, target_is_directory=True)
    # 自环目录链接：防环必须跳过而非死循环
    (source / "self-loop").symlink_to(source, target_is_directory=True)

    resolver = _resolver(tmp_path)
    result = resolver.resolve_path(str(source), snapshot_id="symlink-1")

    snapshot = Path(result.resolved_path)
    assert (snapshot / "Main.java").is_file()
    assert (snapshot / "link-to-real" / "Shared.java").is_file()
    # 自环不会导致快照无限展开：被解析到同一真实目录后跳过
    assert snapshot.is_dir()


def test_git_resolve_skips_content_hash(tmp_path: Path, monkeypatch) -> None:
    """Git 仓库解析后 content_sha256 为 None（commit SHA 已为精确标识）。

    通过 resolve_path（local）确认非 Git 目录会计算哈希，
    而 Git 克隆路径不计算 content_sha256。
    """
    # 非 Git 目录仍计算哈希
    source = tmp_path / "plain"
    source.mkdir()
    (source / "plain.txt").write_text("hello", encoding="utf-8")
    local_result = _resolver(tmp_path).resolve_path(str(source), snapshot_id="hash-test")
    assert local_result.content_sha256 is not None

    # Git 克隆路径：mock _clone 避免真实网络请求
    repo = tmp_path / "git-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "argus@example.test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Argus Test"], check=True)
    (repo / "file.txt").write_text("committed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True)

    def fake_clone(self, repo_url, ref=None, clone_id=""):
        return str(repo.resolve())

    monkeypatch.setattr(
        "argus_py.whitebox.source_resolver.SourceResolver._clone",
        fake_clone,
    )

    resolver = _resolver(tmp_path)
    git_result = resolver.resolve("https://example.com/fake-repo.git")
    assert git_result.content_sha256 is None
    assert git_result.resolved_commit_sha is not None
    assert git_result.source_type == "git"
    # O-07：git 源 source_revision=commit SHA，snapshot_digest=None
    assert git_result.source_revision == git_result.resolved_commit_sha
    assert git_result.snapshot_digest is None


def test_snapshot_excludes_default_build_and_vcs_dirs(tmp_path: Path) -> None:
    """O-07：默认排除 VCS、构建输出与工具缓存，但不排除源码与 wrapper 目录。"""
    source = tmp_path / "source"
    (source / "src" / "main").mkdir(parents=True)
    (source / "src" / "main" / "Main.java").write_text("class Main {}", encoding="utf-8")
    (source / "target" / "classes").mkdir(parents=True)
    (source / "target" / "classes" / "Main.class").write_bytes(b"\xca\xfe\xba\xbe")
    (source / "node_modules" / "pkg").mkdir(parents=True)
    (source / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    # wrapper 目录/文件不得排除
    (source / ".mvn" / "wrapper").mkdir(parents=True)
    (source / ".mvn" / "wrapper" / "maven-wrapper.properties").write_text(
        "distributionUrl=...", encoding="utf-8"
    )
    (source / "mvnw").write_text("#!/bin/sh", encoding="utf-8")

    resolver = _resolver(tmp_path)
    result = resolver.resolve_path(str(source), snapshot_id="excl-1")

    snapshot = Path(result.resolved_path)
    assert (snapshot / "src" / "main" / "Main.java").is_file()
    assert not (snapshot / "target").exists()
    assert not (snapshot / "node_modules").exists()
    assert not (snapshot / ".git").exists()
    assert (snapshot / ".mvn" / "wrapper" / "maven-wrapper.properties").is_file()
    assert (snapshot / "mvnw").is_file()

    metrics = resolver.metrics()
    assert metrics["snapshot_excluded_dirs_total"] >= 3
    assert result.source_revision == result.content_sha256
    assert result.snapshot_digest == result.content_sha256


def test_custom_exclude_dirs_overrides_default(tmp_path: Path) -> None:
    """O-07：自定义排除集覆盖默认集（target 不再被排除）。"""
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / "src" / "a.java").write_text("class A {}", encoding="utf-8")
    (source / "custom_out").mkdir()
    (source / "custom_out" / "x.txt").write_text("x", encoding="utf-8")
    (source / "target").mkdir(parents=True)
    (source / "target" / "t.txt").write_text("t", encoding="utf-8")

    resolver = SourceResolver(
        work_dir=str(tmp_path / "snapshots"),
        exclude_dirs=frozenset({"custom_out"}),
    )
    result = resolver.resolve_path(str(source), snapshot_id="custom")

    snapshot = Path(result.resolved_path)
    assert not (snapshot / "custom_out").exists()
    assert (snapshot / "src" / "a.java").is_file()
    # 覆盖默认集后 target 被保留
    assert (snapshot / "target" / "t.txt").is_file()
    assert resolver.metrics()["snapshot_excluded_dirs_total"] == 1


def test_metrics_accumulate_snapshot_materialize(tmp_path: Path) -> None:
    """O-07：快照物化指标随解析累计。"""
    source = tmp_path / "source"
    source.mkdir()
    (source / "f.bin").write_bytes(b"x" * 1024)

    resolver = _resolver(tmp_path)
    assert resolver.metrics()["snapshot_count"] == 0

    resolver.resolve_path(str(source), snapshot_id="m1")
    resolver.resolve_path(str(source), snapshot_id="m2")

    metrics = resolver.metrics()
    assert metrics["snapshot_count"] == 2
    assert metrics["snapshot_files_total"] == 2
    assert metrics["snapshot_bytes_total"] == 2048
    assert metrics["snapshot_copy_ms_total"] >= 0
    assert metrics["snapshot_hash_ms_total"] >= 0


def test_snapshot_hash_covers_excluded_removal(tmp_path: Path) -> None:
    """O-07：排除目录中的文件不参与内容哈希（排除改变后哈希随之改变）。"""
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "target").mkdir(parents=True)
    (source / "target" / "b.bin").write_bytes(b"z" * 1024)

    resolver = _resolver(tmp_path)
    first = resolver.resolve_path(str(source), snapshot_id="h1")

    # 在排除目录里追加内容——不改变快照内容哈希
    (source / "target" / "c.bin").write_bytes(b"y" * 4096)
    second = resolver.resolve_path(str(source), snapshot_id="h2")

    assert first.content_sha256 == second.content_sha256
