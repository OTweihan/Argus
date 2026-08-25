"""跨平台单实例文件锁。

强制单 Python 进程的最后一层防线：基于 DB/outputs 所在目录的 OS 文件锁。
与普通 pid 文件不同，OS 锁随持锁进程退出（正常或崩溃）由内核自动释放，
不需要也无法可靠地"回收"一个残留的 pid 文件。

- Windows：``msvcrt.locking``（字节锁，锁文件内偏移 0 的 1 字节）。
- POSIX：``fcntl.flock`` 的 ``LOCK_EX | LOCK_NB``（整个文件）。

两者都满足"非阻塞独占 + 进程退出自动释放"的语义。两个进程指向同一
outputs 目录时，只有第一个能拿到锁；拿不到锁的进程应直接拒绝启动。

Windows 差异（跨平台适配的关键点）：
- 字节锁会**禁止其他句柄读写被锁的那一个字节**，因此持锁者信息写入独立的
  ``.owner`` sidecar 文件，而不是锁文件本身；
- 第二个进程打开锁文件时不能截断（``"w"``），否则写入被锁字节区域会直接
  ``PermissionError``，从而把"竞争失败"误判成"IO 错误"。这里统一用
  ``"a+b"`` 追加模式，锁冲突只表现为 ``msvcrt.locking`` 抛 ``OSError``。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

# Windows msvcrt.locking 每次只锁 1 字节；锁区间从文件开头算起。
_LOCK_LENGTH = 1


class SingleInstanceLockError(RuntimeError):
    """获取单实例锁失败。

    细分：

    - ``reason="held"``：锁已被其它进程持有（正常竞争），应拒启。
    - ``reason="unsupported"``：当前平台没有可用的文件锁原语。
    - ``reason="io"``：锁文件无法创建/打开等 IO 问题（与竞争无关）。
    """

    def __init__(self, message: str, reason: str, path: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.path = path


class SingleInstanceLock:
    """进程级独占锁。

    用法::

        lock = SingleInstanceLock(base_dir=OUTPUT_DIR)
        if not lock.acquire(owner="argus:8000"):
            raise ...  # 已被其它进程占用，拒绝启动
        try:
            ...
        finally:
            lock.release()

    锁对象同时是持有标志：``acquired`` 为 True 表示本进程成功持锁。
    """

    def __init__(self, lock_path: str | Path) -> None:
        self._path = Path(lock_path)
        self._owner_path = Path(f"{lock_path}.owner")
        self._file: BinaryIO | None = None
        self.acquired = False

    @property
    def lock_path(self) -> str:
        return str(self._path)

    def acquire(self, owner: str = "") -> bool:
        """尝试非阻塞获取独占锁。

        - 成功：``acquired=True``，返回 True。
        - 锁已被其它进程持有：返回 False（``acquired`` 保持 False）。
        - 平台不支持 / IO 错误：抛 ``SingleInstanceLockError``。

        IO 错误抛异常是为了避免把"锁文件目录不可写"误判为"已有实例在跑"；
        那是部署错误，不是竞争。
        """
        if self.acquired:
            return True
        try:
            if sys.platform == "win32":
                result = self._acquire_win32(owner)
            elif sys.platform in ("linux", "darwin", "freebsd", "openbsd"):
                result = self._acquire_posix(owner)
            else:
                raise SingleInstanceLockError(
                    f"平台 {sys.platform} 不支持文件锁，无法保证单实例",
                    "unsupported",
                    str(self._path),
                )
        except SingleInstanceLockError:
            raise
        except OSError as exc:
            raise SingleInstanceLockError(
                f"获取单实例锁失败：{exc}",
                "io",
                str(self._path),
            ) from exc
        self.acquired = result
        return result

    def release(self) -> None:
        """释放锁并关闭锁文件。

        幂等：未持有或重复调用不报错。进程退出时 OS 也会自动释放，
        ``release`` 只是让同一进程内可复用。
        """
        if not self.acquired:
            return
        try:
            if sys.platform == "win32":
                self._release_win32()
            else:
                self._release_posix()
        except OSError:
            logger.warning("释放单实例锁失败（进程退出时由 OS 兜底释放）", exc_info=True)
        finally:
            self._close_file()
            self.acquired = False

    def __del__(self) -> None:
        # 兜底：对象被 GC 且未显式 release 时仍尽量关闭文件句柄。
        # 持有锁的进程正常退出时，文件描述符随进程关闭，OS 自动释放锁。
        self._close_file()

    # ── 平台实现 ──────────────────────────────────────────────────────────

    def _acquire_win32(self, owner: str) -> bool:
        import msvcrt

        file = self._open_handle()
        try:
            file.seek(0)
            # typeshed 将 msvcrt 内容标记为 win32 专属；linux 平台分析下属性不可见。
            # 两个平台的 ignore 需求互补，由 pyproject.toml 中本模块的
            # warn_unused_ignores=false 统一放行，见 [[tool.mypy.overrides]]。
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, _LOCK_LENGTH)  # type: ignore[attr-defined]
        except OSError:
            file.close()
            return False
        self._file = file
        self._write_owner(owner)
        return True

    def _acquire_posix(self, owner: str) -> bool:
        import fcntl

        file = self._open_handle()
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError:
            file.close()
            return False
        self._file = file
        self._write_owner(owner)
        return True

    def _release_win32(self) -> None:
        import msvcrt

        if self._file is None:
            return
        self._file.seek(0)
        msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, _LOCK_LENGTH)  # type: ignore[attr-defined]

    def _release_posix(self) -> None:
        import fcntl

        if self._file is None:
            return
        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]

    def _open_handle(self) -> BinaryIO:
        """创建/打开锁文件。

        使用 ``"a+b"`` 追加模式，**不截断**：Windows 下第二个进程若用 ``"w"``
        截断，会写入被锁字节区域直接 PermissionError，把竞争误判为 IO 错误。
        锁文件本身只承载锁，持锁者信息写入 sidecar ``.owner``。
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        file = self._path.open("a+b")
        # 保证锁文件至少 1 字节，让 Windows 对偏移 0 的字节锁有明确目标。
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write(b"\n")
            file.flush()
        return file

    def _write_owner(self, owner: str) -> None:
        """把持锁者信息写入独立 sidecar 文件（诊断用，不参与加锁）。

        仅在**成功持锁后**调用，保证 sidecar 始终反映真正的持锁进程——失败进程
        不要覆盖它。Windows 字节锁会禁止其他句柄读写被锁字节，因此信息不能放在
        锁文件内；sidecar 可随时读取。
        """
        if not owner:
            return
        try:
            self._owner_path.write_text(owner, encoding="utf-8")
        except OSError:
            logger.debug("写入持锁者信息失败: %s", self._owner_path, exc_info=True)

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None


def acquire_singleton_lock(
    base_dir: str | Path,
    owner: str = "",
    lock_name: str = ".argus-singleton.lock",
) -> SingleInstanceLock:
    """在 ``base_dir`` 下创建单实例锁并尝试获取。

    ``base_dir`` 使用与 DB 相同的 outputs 目录，保证"指向同一套数据"的两个
    进程必然竞争同一把锁。拿不到锁时返回 ``acquired=False``，由调用方决定拒启。
    """
    lock = SingleInstanceLock(Path(base_dir) / lock_name)
    lock.acquire(owner=owner)
    return lock
