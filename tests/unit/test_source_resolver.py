"""SourceResolver 单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from argus_py.whitebox.source_resolver import SourceResolutionError, SourceResolver


@pytest.fixture
def temp_work_dir() -> str:
    """创建临时工作目录。"""
    d = tempfile.mkdtemp(prefix="test-argus-")
    yield d
    # 测试后清理
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def test_resolve_path_valid_directory(temp_work_dir: str) -> None:
    """验证 resolve_path 返回有效目录的规范化路径。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    result = resolver.resolve_path(temp_work_dir)
    assert result == str(Path(temp_work_dir).resolve())


def test_resolve_path_non_existent(temp_work_dir: str) -> None:
    """验证不存在的路径抛出 SourceResolutionError。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    non_existent = Path(temp_work_dir) / "does-not-exist"
    with pytest.raises(SourceResolutionError, match="路径不存在"):
        resolver.resolve_path(str(non_existent))


def test_resolve_path_file_instead_of_directory(temp_work_dir: str) -> None:
    """验证文件路径（而非目录）抛出 SourceResolutionError。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    file_path = Path(temp_work_dir) / "test.txt"
    file_path.write_text("hello")
    with pytest.raises(SourceResolutionError, match="不是目录"):
        resolver.resolve_path(str(file_path))


def test_resolve_local_path(temp_work_dir: str) -> None:
    """验证 resolve() 对本地目录路径的处理。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    result = resolver.resolve(temp_work_dir)
    assert result == str(Path(temp_work_dir).resolve())


def test_resolve_empty_url_raises(temp_work_dir: str) -> None:
    """验证空 repo_url 抛出 SourceResolutionError。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    with pytest.raises(SourceResolutionError, match="repo_url 不能为空"):
        resolver.resolve("")


def test_resolve_unsupported_scheme(temp_work_dir: str) -> None:
    """验证不支持的协议抛出 SourceResolutionError。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    with pytest.raises(SourceResolutionError, match="不支持的协议"):
        resolver.resolve("ftp://example.com/repo.git")


def test_resolve_ssrf_rejection(temp_work_dir: str) -> None:
    """验证 SSRF 校验拒绝内网地址。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    with pytest.raises(SourceResolutionError, match="SSRF"):
        resolver.resolve("http://169.254.169.254/latest/meta-data/")


def test_cleanup(temp_work_dir: str) -> None:
    """验证 cleanup 不会抛异常。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    # 写入一个文件到 work_dir 以便验证 cleanup
    test_file = Path(temp_work_dir) / "test.txt"
    test_file.write_text("hello")
    resolver.cleanup()
    assert not Path(temp_work_dir).exists()


def test_cleanup_idempotent(temp_work_dir: str) -> None:
    """验证 cleanup 可重复调用。"""
    resolver = SourceResolver(work_dir=temp_work_dir)
    resolver.cleanup()
    # 再次调用不应抛异常
    resolver.cleanup()


def test_sanitize_dir_name() -> None:
    """验证 _sanitize_dir_name 生成安全的目录名。"""
    from argus_py.whitebox.source_resolver import _sanitize_dir_name

    assert _sanitize_dir_name("https://github.com/user/repo.git") == "https_github_com_user_repo_git"
    assert _sanitize_dir_name("git@github.com:user/repo.git") == "git_github_com_user_repo_git"
    assert _sanitize_dir_name("/tmp/path") == "tmp_path"
    # 特殊字符应被替换
    assert ".." not in _sanitize_dir_name("../evil-path")
