"""单实例文件锁 adapter 的单元测试（O-02）。

覆盖跨进程竞争语义：同一路径上第二个锁获取失败、释放后可重获、进程退出后
OS 自动释放。Windows 与 POSIX 分别走 ``msvcrt.locking`` 与 ``fcntl.flock``，
两套实现都满足"非阻塞独占 + 进程退出自动释放"，这里在本机平台验证锁竞争。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from argus_py.infra.singleton_lock import (
    SingleInstanceLock,
    SingleInstanceLockError,
    acquire_singleton_lock,
)


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / ".argus-singleton.lock"


class TestSingleInstanceLock:
    def test_acquire_succeeds_first(self, lock_path: Path) -> None:
        lock = SingleInstanceLock(lock_path)
        assert lock.acquire(owner="pid=1") is True
        assert lock.acquired is True
        # 锁文件存在；持锁者信息写入 sidecar（Windows 字节锁禁止读取被锁字节）。
        assert lock_path.exists()
        assert lock_path.with_name(f"{lock_path.name}.owner").exists()
        lock.release()

    def test_second_acquire_conflicts_until_release(self, lock_path: Path) -> None:
        first = SingleInstanceLock(lock_path)
        assert first.acquire() is True
        try:
            second = SingleInstanceLock(lock_path)
            assert second.acquire() is False
            assert second.acquired is False
        finally:
            first.release()

        # 释放后可重获。
        third = SingleInstanceLock(lock_path)
        assert third.acquire() is True
        assert third.acquired is True
        third.release()

    def test_acquire_is_idempotent(self, lock_path: Path) -> None:
        lock = SingleInstanceLock(lock_path)
        assert lock.acquire() is True
        # 重复 acquire 返回 True，不重新尝试。
        assert lock.acquire() is True
        lock.release()

    def test_release_is_idempotent(self, lock_path: Path) -> None:
        lock = SingleInstanceLock(lock_path)
        lock.acquire()
        lock.release()
        # 未持有 / 重复 release 不抛错。
        lock.release()
        assert lock.acquired is False

    def test_acquire_writes_owner_info(self, lock_path: Path) -> None:
        lock = SingleInstanceLock(lock_path)
        lock.acquire(owner="pid=4242; app=argus")
        owner_path = lock_path.with_name(f"{lock_path.name}.owner")
        assert owner_path.read_text(encoding="utf-8") == "pid=4242; app=argus"
        lock.release()

    def test_failed_acquire_does_not_overwrite_holder_owner(self, lock_path: Path) -> None:
        """持锁者信息只反映真正的持锁进程：竞争失败的进程不应覆盖它。"""
        first = SingleInstanceLock(lock_path)
        assert first.acquire(owner="holder") is True
        try:
            loser = SingleInstanceLock(lock_path)
            assert loser.acquire(owner="loser") is False
            owner_path = lock_path.with_name(f"{lock_path.name}.owner")
            assert owner_path.read_text(encoding="utf-8") == "holder"
        finally:
            first.release()

    def test_io_error_is_distinguished_from_contention(self, lock_path: Path) -> None:
        """锁文件路径不可用属于 IO 错误，应抛异常而不是误判为"已有实例"。"""
        # 用目录占住锁文件路径，open 会抛 IsADirectoryError（OSError 子类）。
        bad_path = lock_path.parent / "not-a-file.lock"
        bad_path.mkdir()
        blocked = SingleInstanceLock(bad_path)
        with pytest.raises(SingleInstanceLockError) as exc:
            blocked.acquire()
        assert exc.value.reason == "io"


class TestAcquireSingletonLockHelper:
    def test_helper_acquires_in_base_dir(self, tmp_path: Path) -> None:
        lock = acquire_singleton_lock(tmp_path, owner="pid=1", lock_name="x.lock")
        assert lock.acquired is True
        assert (tmp_path / "x.lock").exists()
        lock.release()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows 上无 fcntl，POSIX 分支无需在此验证",
)
class TestPosixLock:
    """POSIX 分支（linux/macOS CI）验证：与 Windows 分支相同的竞争语义。"""

    def test_posix_acquire_conflict(self, lock_path: Path) -> None:
        first = SingleInstanceLock(lock_path)
        assert first.acquire() is True
        second = SingleInstanceLock(lock_path)
        assert second.acquire() is False
        first.release()
        third = SingleInstanceLock(lock_path)
        assert third.acquire() is True
        third.release()
