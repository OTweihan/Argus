"""诊断日志文件 IO：反向块读、定点读行、上下文窗口。

定位器类型使用 ``diagnostics_cursors.EventLocator``（公开值对象）。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from pathlib import Path

from argus_py.observability.diagnostics_cursors import EventLocator
from argus_py.observability.diagnostics_models import DiagnosticsNotFoundError

# 反向读块大小（D-05）：避免单次读入整个扫描预算。
_REVERSE_READ_CHUNK_BYTES = 256 * 1024


def _iter_reverse_line_window(
    path: Path,
    max_bytes: int,
    *,
    end_offset: int | None = None,
    chunk_size: int = _REVERSE_READ_CHUNK_BYTES,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[Iterator[tuple[int, str]], int, bool]:
    """在字节预算内从指定上界按块读取窗口内完整行（旧→新，D-05）。

    返回 ``(line_iter, consumed, truncated)``：
    - ``consumed`` / ``truncated`` 在打开窗口时即可确定（按计划窗口计费），
      不依赖迭代是否提前结束，也不写入实例状态；
    - 不一次 ``read(max_bytes)``；跨块半行正确拼接；
    - 调用方负责 top-heap / reverse。

    **设计折中（D-05 本阶段）**：分块 IO 降低单次 read 峰值；在文件内
    timestamp 可能回退的前提下，仍需扫完整字节窗才能保证 top-N 正确
    （不能「读够 limit 匹配就停」）。匹配早停需单调性假设或两阶段扫描，
    留待后续。可选 ``should_stop`` 仅用于协作取消，提前结束时仍按整窗
    计费 consumed（与预算契约一致：窗口已划定）。
    """

    def _empty() -> Iterator[tuple[int, str]]:
        return iter(())

    try:
        size = path.stat().st_size
        end = size if end_offset is None else min(size, max(0, end_offset))
        if end <= 0 or max_bytes <= 0:
            return _empty(), 0, False

        budget = max(0, int(max_bytes))
        # 允许测试传入小块；生产默认 _REVERSE_READ_CHUNK_BYTES 已足够大。
        block = max(1, int(chunk_size))
        # 窗口 [window_start, end)：先定界再正向分块扫，避免整窗一次 read。
        window_start = max(0, end - budget)
        truncated = window_start > 0
        consumed = end - window_start

        def _lines() -> Iterator[tuple[int, str]]:
            carry = b""
            file_pos = window_start
            # 窗口起点可能落在半行：持续丢弃到首个 \n（可跨块）。
            # 局部变量即可（不封闭外层 truncated）。
            skip_partial = truncated
            with path.open("rb") as file:
                while file_pos < end:
                    if should_stop is not None and should_stop():
                        return
                    take = min(block, end - file_pos)
                    file.seek(file_pos)
                    data = file.read(take)
                    if not data:
                        break
                    buf = carry + data
                    abs_start = file_pos - len(carry)
                    consume_from = 0
                    if skip_partial:
                        nl = buf.find(b"\n")
                        if nl < 0:
                            # 半行仍未结束：丢掉已读前缀，继续向后找行界
                            carry = b""
                            file_pos += len(data)
                            continue
                        consume_from = nl + 1
                        skip_partial = False

                    view = buf[consume_from:]
                    view_base = abs_start + consume_from
                    last_nl = view.rfind(b"\n")
                    if last_nl < 0:
                        carry = view
                        file_pos += len(data)
                        continue
                    complete = view[: last_nl + 1]
                    carry = view[last_nl + 1 :]
                    offset = view_base
                    for raw_line in complete.splitlines(keepends=True):
                        line_bytes = raw_line.rstrip(b"\r\n")
                        yield offset, line_bytes.decode("utf-8", errors="replace")
                        offset += len(raw_line)
                    file_pos += len(data)

                if skip_partial:
                    # 整窗无完整行
                    return

                # end 落在行中：丢弃半行；end==size 且无尾 \n：产出最后一行。
                if carry and end >= size:
                    yield file_pos - len(carry), carry.decode("utf-8", errors="replace")

        return _lines(), consumed, truncated
    except OSError:
        return _empty(), 0, False


def _read_reverse_lines(
    path: Path,
    max_bytes: int,
    *,
    end_offset: int | None = None,
    chunk_size: int = _REVERSE_READ_CHUNK_BYTES,
) -> tuple[list[tuple[int, str]], int, bool]:
    """在字节预算内从指定上界读取完整行，返回 **新→旧** 记录。

    D-05：按块扫窗口，避免单次读入整个扫描预算。
    """
    line_iter, consumed, truncated = _iter_reverse_line_window(
        path,
        max_bytes,
        end_offset=end_offset,
        chunk_size=chunk_size,
    )
    records = list(line_iter)
    records.reverse()
    return records, consumed, truncated


def _read_line_at_offset(
    path: Path,
    offset: int,
    max_bytes: int | None = None,
) -> tuple[str, int, bool]:
    """按字节偏移读取一条完整行，并验证偏移确实位于行首。"""
    try:
        size = path.stat().st_size
        if offset < 0 or offset >= size:
            raise DiagnosticsNotFoundError("日志事件已被轮转或截断")
        consumed = 0
        with path.open("rb") as file:
            if offset:
                if max_bytes is not None and max_bytes <= 0:
                    return "", consumed, True
                file.seek(offset - 1)
                if file.read(1) != b"\n":
                    raise DiagnosticsNotFoundError("日志事件字节偏移不是行首")
                consumed += 1
            remaining = None if max_bytes is None else max(0, max_bytes - consumed)
            if remaining == 0:
                return "", consumed, True
            file.seek(offset)
            raw = file.readline(-1 if remaining is None else remaining)
        consumed += len(raw)
        if not raw:
            raise DiagnosticsNotFoundError("日志事件已被轮转或截断")
        if offset + len(raw) < size and not raw.endswith(b"\n"):
            return "", consumed, True
        return raw.rstrip(b"\r\n").decode("utf-8", errors="replace"), consumed, False
    except OSError as exc:
        raise DiagnosticsNotFoundError(f"日志文件不可读：{path.name}") from exc


def _read_line_at_number(
    path: Path,
    line_no: int,
    max_bytes: int | None = None,
) -> tuple[int, str, int, bool]:
    """流式读取旧版行号定位器，并返回对应字节偏移。"""
    try:
        size = path.stat().st_size
        consumed = 0
        offset = 0
        with path.open("rb") as file:
            for current in range(1, line_no + 1):
                remaining = None if max_bytes is None else max(0, max_bytes - consumed)
                if remaining == 0:
                    return offset, "", consumed, True
                raw = file.readline(-1 if remaining is None else remaining)
                if not raw:
                    raise DiagnosticsNotFoundError("日志行已被轮转或截断")
                if offset + len(raw) < size and not raw.endswith(b"\n"):
                    return offset, "", consumed + len(raw), True
                if current == line_no:
                    return (
                        offset,
                        raw.rstrip(b"\r\n").decode("utf-8", errors="replace"),
                        consumed + len(raw),
                        False,
                    )
                offset += len(raw)
                consumed += len(raw)
    except OSError as exc:
        raise DiagnosticsNotFoundError(f"日志文件不可读：{path.name}") from exc

    raise DiagnosticsNotFoundError("日志行已被轮转或截断")


def _line_number_at_offset(path: Path, offset: int) -> int:
    """计算字节偏移对应的 1-based 行号；仅详情/上下文请求使用。"""
    try:
        size = path.stat().st_size
        if offset < 0 or offset >= size:
            raise DiagnosticsNotFoundError("日志事件已被轮转或截断")
        remaining = offset
        newlines = 0
        with path.open("rb") as file:
            while remaining:
                chunk = file.read(min(64 * 1024, remaining))
                if not chunk:
                    raise DiagnosticsNotFoundError("日志事件已被轮转或截断")
                newlines += chunk.count(b"\n")
                remaining -= len(chunk)
        return newlines + 1
    except OSError as exc:
        raise DiagnosticsNotFoundError(f"日志文件不可读：{path.name}") from exc


def _resolve_locator(path: Path, locator: EventLocator) -> tuple[int, str]:
    """流式解析新字节偏移或旧行号定位器，不加载完整文件。"""
    if locator.line is not None:
        _, line, _, _ = _read_line_at_number(path, locator.line)
        return locator.line, line
    assert locator.offset is not None
    line, _, _ = _read_line_at_offset(path, locator.offset)
    return _line_number_at_offset(path, locator.offset), line


def _read_context_window(
    path: Path,
    locator: EventLocator,
    before: int,
    after: int,
) -> tuple[int, str, list[tuple[int, str]]]:
    """单次流式扫描定位目标，并仅保留目标前后的有限行窗口。"""
    previous: deque[tuple[int, str]] = deque(maxlen=before)
    try:
        offset = 0
        with path.open("rb") as file:
            line_no = 0
            while raw := file.readline():
                line_no += 1
                current_offset = offset
                offset += len(raw)
                line = raw.rstrip(b"\r\n").decode("utf-8", errors="replace")
                is_target = (
                    locator.line == line_no
                    if locator.line is not None
                    else locator.offset == current_offset
                )
                if not is_target:
                    previous.append((line_no, line))
                    continue

                context = [*previous, (line_no, line)]
                for _ in range(after):
                    following = file.readline()
                    if not following:
                        break
                    line_no += 1
                    context.append(
                        (
                            line_no,
                            following.rstrip(b"\r\n").decode("utf-8", errors="replace"),
                        )
                    )
                target_line_no = context[len(previous)][0]
                return target_line_no, line, context
    except OSError as exc:
        raise DiagnosticsNotFoundError(f"日志文件不可读：{path.name}") from exc
    raise DiagnosticsNotFoundError("日志事件已被轮转或截断")
