"""诊断日志仓储（docs/optimizations/diagnostics-center-plan.md 4.3 / 第 18 章）。

第一阶段本地文件实现 ``FileDiagnosticsLogStore``：直接扫描 JSONL 运行日志与
dev 会话日志，游标分页、字节预算与路径安全约束全部内聚在本模块。

设计要点：

- 命名避开任务步骤日志既有仓储，见方案 4.3；
- 事件 ID 是可解码定位器（新格式为相对路径 + 字节偏移 + 时间戳，兼容旧行号格式），
  不引入第二套索引存储；文件轮转后定位失效属预期行为，按 404 处理（JSONL 是事实源）；
- 所有路径由本模块从日志根目录推导，外部输入只有事件 ID 与 run_id，
  均做穿越校验（方案 18.3）；
- 同步实现；调用方（route 层）必须经 ``run_in_thread`` 执行（方案第 17 章）。
"""

from __future__ import annotations

import base64
import json
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 常量 ────────────────────────────────────────────────────────────────────

# dev 会话目录名：dev.mjs timestampForDirectory 生成的 yyyyMMdd-HHmmss
_RUN_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}$")
# dev 会话日志行：`2026-08-05T16:42:09.120Z [python][stdout] 内容`
_DEV_LINE_PATTERN = re.compile(r"^(\S+) \[([a-z]+)\]\[([a-z]+)\] (.*)$", re.IGNORECASE)

_COMPONENTS = frozenset({"python", "java", "frontend", "launcher", "system", "web"})
# 仍主要依赖 dev 会话目录的组件（运行时 JSONL 尚未覆盖或仅作补充）
_DEV_ONLY_COMPONENTS = frozenset({"frontend", "launcher"})
# runtime 子目录 → 诊断 component；python 保持历史路径 runtime/python/argus*
_RUNTIME_COMPONENT_DIRS: dict[str, str] = {
    "python": "python",
    "java": "java",
    "web": "web",
    "system": "system",
}
_LEVEL_ORDER: dict[str, int] = {
    "TRACE": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}

_DEFAULT_SCAN_BUDGET_BYTES = 64 * 1024 * 1024
_MAX_CONTEXT_LINES = 200

# 会话内参与检索的文件；combined.log 是其余三份的超集，跳过避免重复命中
_SEARCHABLE_RUN_FILES = ("python.log", "java.log", "frontend.log")
_ALL_RUN_FILES = (*_SEARCHABLE_RUN_FILES, "combined.log")


@dataclass(frozen=True)
class DiagnosticsQuery:
    """日志检索条件（字段命名沿用方案 8.2，Python 侧 snake_case）。"""

    time_from: datetime | None = None
    time_to: datetime | None = None
    component: str | None = None
    level: str | None = None
    keyword: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class DiagnosticsEvent:
    """统一诊断日志事件（wire 字段 camelCase，见方案 14.2）。"""

    event_id: str
    timestamp: str
    level: str
    component: str
    module: str
    message: str
    request_id: str | None = None
    run_id: str | None = None
    exception: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        """转为 camelCase wire 字典（不含 raw，raw 仅详情返回）。"""
        return {
            "eventId": self.event_id,
            "timestamp": self.timestamp,
            "level": self.level,
            "component": self.component,
            "module": self.module,
            "message": self.message,
            "requestId": self.request_id,
            "runId": self.run_id,
            "exception": self.exception,
        }


@dataclass(frozen=True)
class DiagnosticsPage:
    """游标分页结果（方案 8.6）。"""

    items: list[DiagnosticsEvent]
    next_cursor: str | None
    has_more: bool
    scan_limited: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "items": [event.to_wire() for event in self.items],
            "nextCursor": self.next_cursor,
            "hasMore": self.has_more,
            "scanLimited": self.scan_limited,
        }


@dataclass(frozen=True)
class RunFileInfo:
    name: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started_at: str
    files: list[RunFileInfo]
    total_bytes: int

    def to_wire(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "startedAt": self.started_at,
            "files": [
                {"name": f.name, "sizeBytes": f.size_bytes, "modifiedAt": f.modified_at}
                for f in self.files
            ],
            "totalBytes": self.total_bytes,
        }


class DiagnosticsNotFoundError(LookupError):
    """事件或启动会话不存在（路由层转 404）。"""


class DiagnosticsBadRequestError(ValueError):
    """非法游标 / 非法标识（路由层转 400）。"""


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _b64_encode(payload: str) -> str:
    """URL 安全 base64（去填充，便于直接作为路径参数）。"""
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _encode_event_id(rel_path: str, line_no: int) -> str:
    """编码旧版行号事件 ID（保留给已有链接与兼容性测试）。"""
    return _b64_encode(json.dumps({"f": rel_path, "l": line_no}, ensure_ascii=False))


@dataclass(frozen=True)
class _EventLocator:
    file: str
    line: int | None = None
    offset: int | None = None
    timestamp: str | None = None


def _encode_event_locator(locator: _EventLocator) -> str:
    payload: dict[str, object] = {"f": locator.file}
    if locator.offset is not None:
        payload["o"] = locator.offset
    elif locator.line is not None:
        payload["l"] = locator.line
    else:  # pragma: no cover - 内部构造器保证至少有一种位置
        raise ValueError("事件定位器缺少行号或字节偏移")
    if locator.timestamp is not None:
        payload["t"] = locator.timestamp
    return _b64_encode(json.dumps(payload, ensure_ascii=False))


def _decode_event_id(event_id: str) -> _EventLocator:
    try:
        payload = json.loads(_b64_decode(event_id))
        rel_path = str(payload["f"])
        line_no = int(payload["l"]) if "l" in payload else None
        offset = int(payload["o"]) if "o" in payload else None
        timestamp = str(payload["t"]) if payload.get("t") is not None else None
    except Exception as exc:  # noqa: BLE001 — 任何畸形输入都视为不存在
        raise DiagnosticsNotFoundError(f"事件不存在或已轮转：{event_id!r}") from exc
    invalid_position = (line_no is None) == (offset is None)
    if (
        invalid_position
        or (line_no is not None and line_no < 1)
        or (offset is not None and offset < 0)
        or not rel_path
        or "\x00" in rel_path
    ):
        raise DiagnosticsNotFoundError(f"事件不存在或已轮转：{event_id!r}")
    return _EventLocator(
        file=rel_path,
        line=line_no,
        offset=offset,
        timestamp=timestamp,
    )


@dataclass(frozen=True)
class _CursorPos:
    locator: _EventLocator
    timestamp: str


def _encode_cursor(event: DiagnosticsEvent) -> str:
    locator = _decode_event_id(event.event_id)
    payload: dict[str, object] = {"f": locator.file, "t": event.timestamp}
    if locator.offset is not None:
        payload["o"] = locator.offset
    else:
        payload["l"] = locator.line
    return _b64_encode(json.dumps(payload, ensure_ascii=False))


def _decode_cursor(cursor: str | None) -> _CursorPos | None:
    if not cursor:
        return None
    try:
        payload = json.loads(_b64_decode(cursor))
        line_no = int(payload["l"]) if "l" in payload else None
        offset = int(payload["o"]) if "o" in payload else None
        pos = _CursorPos(
            locator=_EventLocator(
                file=str(payload["f"]),
                line=line_no,
                offset=offset,
                timestamp=str(payload["t"]),
            ),
            timestamp=str(payload["t"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise DiagnosticsBadRequestError("非法分页游标") from exc
    locator = pos.locator
    invalid_position = (locator.line is None) == (locator.offset is None)
    if (
        invalid_position
        or (locator.line is not None and locator.line < 1)
        or (locator.offset is not None and locator.offset < 0)
        or not locator.file
        or "\x00" in locator.file
    ):
        raise DiagnosticsBadRequestError("非法分页游标")
    return pos


class FileDiagnosticsLogStore:
    """本地文件诊断日志仓储。

    覆盖两类数据源：

    - ``runtime/{python,java,web,system}/``：结构化 JSON Lines
      （Python ``argus*``、Java ``*.jsonl``、前端异常与系统事件）；
    - ``dev/<run-id>/{python,java,frontend}.log``：dev.mjs 会话纯文本日志，
      作为开发态补充来源（与 runtime 并存时按文件独立定位，不跨源去重）。
    """

    def __init__(self, logs_root: Path) -> None:
        self._logs_root = Path(logs_root).resolve()
        self._logs_root.mkdir(parents=True, exist_ok=True)
        self._runtime_root = self._logs_root / "runtime"
        self._runtime_dir = self._runtime_root / "python"
        self._dev_dir = self._logs_root / "dev"
        self._scan_max_bytes = _DEFAULT_SCAN_BUDGET_BYTES

    def set_scan_budget(self, max_bytes: int) -> None:
        """设置单次查询累计扫描字节上限（来自 server.yaml diagnostics 配置）。"""
        self._scan_max_bytes = max(1024 * 1024, int(max_bytes))

    @property
    def logs_root(self) -> Path:
        """日志根目录（服务状态聚合读取用量用）。"""
        return self._logs_root

    # ── 公开接口（对应方案 4.3）─────────────────────────────────────────

    def search(self, query: DiagnosticsQuery) -> DiagnosticsPage:
        """按条件检索日志，新→旧返回至多 limit 条。"""
        component = self._normalize_component(query.component)
        run_id = self._validate_run_id(query.run_id) if query.run_id else None
        limit = max(1, min(query.limit, 500))
        cursor_pos = _decode_cursor(query.cursor)
        candidates = self._candidate_files(component, run_id)
        budget = self._scan_max_bytes
        cursor_pos, cursor_exact, cursor_consumed, cursor_limited = self._prepare_cursor(
            cursor_pos,
            candidates,
            budget,
        )
        budget -= cursor_consumed
        matcher = _EventMatcher(query, cursor_pos, cursor_exact=cursor_exact)

        collected: list[DiagnosticsEvent] = []
        scan_limited = cursor_limited
        has_more = False

        cursor_file_index: int | None = None
        if cursor_exact and cursor_pos is not None:
            cursor_file_index = next(
                index
                for index, (_, rel_path) in enumerate(candidates)
                if rel_path == cursor_pos.locator.file
            )

        for index, (path, rel_path) in enumerate(candidates):
            if cursor_file_index is not None and index < cursor_file_index:
                continue
            if budget <= 0:
                # 还有未读候选文件却被预算截断：提示前端缩小时间范围。
                scan_limited = True
                break
            end_offset = (
                cursor_pos.locator.offset
                if cursor_file_index == index and cursor_pos is not None
                else None
            )
            records, consumed, file_truncated = self._read_reverse_lines(
                path,
                budget,
                end_offset=end_offset,
            )
            budget -= consumed
            if file_truncated:
                scan_limited = True
            for offset, line in records:
                event = self._build_event(
                    line,
                    rel_path,
                    _EventLocator(file=rel_path, offset=offset),
                )
                if event is None:
                    continue
                verdict = matcher.match(event)
                if verdict is not True:
                    continue
                if len(collected) >= limit:
                    has_more = True
                    break
                collected.append(event)
            if has_more:
                break

        next_cursor = (
            _encode_cursor(collected[-1]) if collected and (has_more or scan_limited) else None
        )
        return DiagnosticsPage(
            items=collected,
            next_cursor=next_cursor,
            has_more=has_more,
            scan_limited=scan_limited,
        )

    def get_detail(self, event_id: str) -> dict[str, Any]:
        """返回单条事件完整内容（含原始 JSON 与文件定位，方案 8.4）。"""
        locator = _decode_event_id(event_id)
        path, rel_path = self._resolve_within_root(locator.file)
        line_no, line = self._resolve_locator(path, locator)
        detail = self._detail_from_line(line, rel_path, line_no, locator=locator)
        if locator.timestamp is not None and detail["event"].timestamp != locator.timestamp:
            raise DiagnosticsNotFoundError("日志事件已被轮转或内容已变化")
        return detail

    def get_context(
        self, event_id: str, before: int = 20, after: int = 20
    ) -> list[DiagnosticsEvent]:
        """返回同一文件内前后若干条事件（方案 8.5：上下文限定同组件同文件）。"""
        before = max(0, min(before, _MAX_CONTEXT_LINES))
        after = max(0, min(after, _MAX_CONTEXT_LINES))
        locator = _decode_event_id(event_id)
        path, rel_path = self._resolve_within_root(locator.file)
        line_no, target_line, context_lines = self._read_context_window(
            path,
            locator,
            before,
            after,
        )
        target = self._detail_from_line(
            target_line,
            rel_path,
            line_no,
            locator=locator,
        )["event"]
        if locator.timestamp is not None and target.timestamp != locator.timestamp:
            raise DiagnosticsNotFoundError("日志事件已被轮转或内容已变化")
        events: list[DiagnosticsEvent] = []
        for current, line in context_lines:
            try:
                events.append(self._detail_from_line(line, rel_path, current)["event"])
            except DiagnosticsNotFoundError:
                continue  # 损坏行在上下文窗口中跳过，不让整段上下文失败（方案 25.4）
        return events

    def search_by_request_id(self, request_id: str, limit: int = 200) -> list[DiagnosticsEvent]:
        """按 requestId 检索完整调用过程，按时间正序返回（方案 17.6）。"""
        page = self.search(DiagnosticsQuery(request_id=request_id, limit=min(limit, 500)))
        return sorted(page.items, key=lambda e: e.timestamp)

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """列出启动会话（dev 目录），新会话在前。"""
        runs: list[RunSummary] = []
        if not self._dev_dir.is_dir():
            return runs
        for entry in sorted(self._dev_dir.iterdir(), reverse=True):
            if not entry.is_dir() or not _RUN_ID_PATTERN.match(entry.name):
                continue
            runs.append(self._summarize_run(entry))
            if len(runs) >= max(1, limit):
                break
        return runs

    def get_run_detail(self, run_id: str) -> RunSummary:
        """返回单个启动会话元数据。"""
        return self._summarize_run(self._resolve_run_dir(run_id))

    def search_run_logs(self, run_id: str, query: DiagnosticsQuery) -> DiagnosticsPage:
        """检索指定启动会话内的日志（方案 17.7 runs/{runId}/logs）。"""
        return self.search(
            DiagnosticsQuery(
                time_from=query.time_from,
                time_to=query.time_to,
                component=query.component,
                level=query.level,
                keyword=query.keyword,
                request_id=query.request_id,
                run_id=self._validate_run_id(run_id),
                limit=max(1, query.limit),
                cursor=query.cursor,
            )
        )

    # ── 内部实现 ────────────────────────────────────────────────────────

    def _normalize_component(self, component: str | None) -> str | None:
        if not component:
            return None
        value = component.strip().lower()
        if value in ("", "all"):
            return None
        if value not in _COMPONENTS:
            raise DiagnosticsBadRequestError(f"未知组件：{component}")
        return value

    def _validate_run_id(self, run_id: str) -> str:
        if not _RUN_ID_PATTERN.match(run_id):
            raise DiagnosticsBadRequestError(f"非法的启动会话 ID：{run_id!r}")
        return run_id

    def _resolve_run_dir(self, run_id: str) -> Path:
        self._validate_run_id(run_id)
        run_dir = (self._dev_dir / run_id).resolve()
        if not run_dir.is_relative_to(self._logs_root) or not run_dir.is_dir():
            raise DiagnosticsNotFoundError(f"启动会话不存在：{run_id}")
        return run_dir

    def _resolve_within_root(self, rel_path: str) -> tuple[Path, str]:
        normalized = rel_path.replace("\\", "/")
        candidate = (self._logs_root / normalized).resolve()
        if not candidate.is_relative_to(self._logs_root):
            raise DiagnosticsNotFoundError("非法日志路径")
        if not candidate.is_file():
            raise DiagnosticsNotFoundError(f"日志文件已清理或轮转：{normalized}")
        return candidate, normalized

    def _candidate_files(self, component: str | None, run_id: str | None) -> list[tuple[Path, str]]:
        """返回待扫描文件（新→旧），元素为 (绝对路径, 相对日志根的 POSIX 路径)。"""

        def _entry(path: Path) -> tuple[Path, str]:
            resolved = path.resolve()
            return resolved, resolved.relative_to(self._logs_root).as_posix()

        if run_id:
            run_dir = self._resolve_run_dir(run_id)
            wanted: tuple[str, ...] = _SEARCHABLE_RUN_FILES
            if component in ("python", "java", "frontend"):
                wanted = (f"{component}.log",)
            files = [_entry(run_dir / name) for name in wanted if (run_dir / name).is_file()]
            return sorted(files, key=lambda pair: _mtime(pair[0]), reverse=True)

        results: list[tuple[Path, str]] = []

        if component in _DEV_ONLY_COMPONENTS:
            # 前端 / launcher 仍以 dev 会话为主。
            for run_name in self._list_run_dirs(limit=20):
                candidate = self._dev_dir / run_name / f"{component}.log"
                if candidate.is_file():
                    results.append(_entry(candidate))
            return sorted(results, key=lambda pair: _mtime(pair[0]), reverse=True)

        # 运行时结构化日志：按组件过滤或全量合并。
        results.extend(self._runtime_candidate_files(component, _entry))

        # Java 尚无 runtime JSONL 时回退最近 dev 会话，避免完全不可见。
        if component in (None, "java"):
            has_java_runtime = any(rel.startswith("runtime/java/") for _, rel in results)
            if not has_java_runtime:
                for run_name in self._list_run_dirs(limit=20):
                    candidate = self._dev_dir / run_name / "java.log"
                    if candidate.is_file():
                        results.append(_entry(candidate))

        # 去重（同一绝对路径可能被多次加入）后按 mtime 新→旧
        deduped: dict[str, tuple[Path, str]] = {}
        for path, rel in results:
            deduped[str(path)] = (path, rel)
        return sorted(deduped.values(), key=lambda pair: _mtime(pair[0]), reverse=True)

    def _runtime_candidate_files(
        self,
        component: str | None,
        entry_fn: Callable[[Path], tuple[Path, str]],
    ) -> list[tuple[Path, str]]:
        """收集 runtime 下结构化日志文件。"""
        if not self._runtime_root.is_dir():
            return []

        dirs: list[tuple[str, Path]] = []
        if component is None:
            for name in _RUNTIME_COMPONENT_DIRS:
                dirs.append((name, self._runtime_root / name))
        elif component in _RUNTIME_COMPONENT_DIRS:
            dirs.append((component, self._runtime_root / component))
        else:
            return []

        files: list[tuple[Path, str]] = []
        for name, directory in dirs:
            if not directory.is_dir():
                continue
            if name == "python":
                # 历史路径：argus.log / argus.error.log / 轮转备份 argus.log.1
                for path in directory.glob("argus*"):
                    if path.is_file() and (
                        path.suffix == ".log" or re.fullmatch(r"\.\d+", path.suffix)
                    ):
                        files.append(entry_fn(path))
            else:
                for path in directory.iterdir():
                    if not path.is_file():
                        continue
                    # JSONL 正式扩展名；兼容 .log 内容为 JSON Lines 的落盘
                    if path.suffix.lower() in {".jsonl", ".log"} or re.fullmatch(
                        r"\.\d+", path.suffix
                    ):
                        files.append(entry_fn(path))
        return files

    def _list_run_dirs(self, limit: int) -> list[str]:
        if not self._dev_dir.is_dir():
            return []
        names = sorted(
            entry.name
            for entry in self._dev_dir.iterdir()
            if entry.is_dir() and _RUN_ID_PATTERN.match(entry.name)
        )
        return names[-limit:] if limit > 0 else []

    def _read_reverse_lines(
        self,
        path: Path,
        max_bytes: int,
        *,
        end_offset: int | None = None,
    ) -> tuple[list[tuple[int, str]], int, bool]:
        """在字节预算内从指定上界逆序读取完整行，返回新→旧记录。"""
        try:
            size = path.stat().st_size
            end = size if end_offset is None else min(size, max(0, end_offset))
            read_size = min(end, max(0, max_bytes))
            start = end - read_size
            with path.open("rb") as file:
                file.seek(start)
                raw = file.read(read_size)
        except OSError:
            return [], 0, False

        truncated = start > 0
        content_start = start
        if truncated:
            boundary = raw.find(b"\n")
            if boundary < 0:
                return [], len(raw), True
            content_start += boundary + 1
            raw = raw[boundary + 1 :]

        records: list[tuple[int, str]] = []
        offset = content_start
        for raw_line in raw.splitlines(keepends=True):
            line_bytes = raw_line.rstrip(b"\r\n")
            records.append((offset, line_bytes.decode("utf-8", errors="replace")))
            offset += len(raw_line)
        records.reverse()
        return records, read_size, truncated

    def _read_line_at_offset(
        self,
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
        self,
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

    def _line_number_at_offset(self, path: Path, offset: int) -> int:
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

    def _resolve_locator(self, path: Path, locator: _EventLocator) -> tuple[int, str]:
        """流式解析新字节偏移或旧行号定位器，不加载完整文件。"""
        if locator.line is not None:
            _, line, _, _ = self._read_line_at_number(path, locator.line)
            return locator.line, line
        assert locator.offset is not None
        line, _, _ = self._read_line_at_offset(path, locator.offset)
        return self._line_number_at_offset(path, locator.offset), line

    def _read_context_window(
        self,
        path: Path,
        locator: _EventLocator,
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

    def _prepare_cursor(
        self,
        cursor: _CursorPos | None,
        candidates: list[tuple[Path, str]],
        max_bytes: int,
    ) -> tuple[_CursorPos | None, bool, int, bool]:
        """在预算内校验游标，并把有效旧行号位置规范化为字节偏移。"""
        if cursor is None:
            return None, False, 0, False
        paths = {rel_path: path for path, rel_path in candidates}
        path = paths.get(cursor.locator.file)
        if path is None:
            return cursor, False, 0, False
        try:
            if cursor.locator.offset is not None:
                offset = cursor.locator.offset
                line, consumed, limited = self._read_line_at_offset(
                    path,
                    offset,
                    max_bytes,
                )
            else:
                assert cursor.locator.line is not None
                offset, line, consumed, limited = self._read_line_at_number(
                    path,
                    cursor.locator.line,
                    max_bytes,
                )
        except DiagnosticsNotFoundError:
            return cursor, False, 0, False
        if limited:
            return cursor, False, min(consumed, max_bytes), True
        normalized = _CursorPos(
            locator=_EventLocator(
                file=cursor.locator.file,
                offset=offset,
                timestamp=cursor.timestamp,
            ),
            timestamp=cursor.timestamp,
        )
        event = self._build_event(line, cursor.locator.file, normalized.locator)
        if event is None:
            return cursor, False, consumed, False
        if event.timestamp != cursor.timestamp:
            return cursor, False, consumed, False
        return normalized, True, consumed, False

    def _build_event(
        self,
        line: str,
        rel_path: str,
        locator: _EventLocator,
    ) -> DiagnosticsEvent | None:
        stripped = line.strip()
        if not stripped:
            return None
        builder = (
            self._build_dev_event if rel_path.startswith("dev/") else self._build_runtime_event
        )
        return builder(stripped, rel_path, locator)

    def _build_runtime_event(
        self, line: str, rel_path: str, locator: _EventLocator
    ) -> DiagnosticsEvent | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        timestamp = str(payload.get("timestamp") or "")
        exception = payload.get("exception") or payload.get("errorStack")
        component = _component_from_runtime_path(rel_path, payload)
        return DiagnosticsEvent(
            event_id=_encode_event_locator(
                _EventLocator(
                    file=rel_path,
                    line=locator.line,
                    offset=locator.offset,
                    timestamp=timestamp or "1970-01-01T00:00:00+00:00",
                )
            ),
            timestamp=timestamp or "1970-01-01T00:00:00+00:00",
            level=str(payload.get("level") or "INFO").upper(),
            component=component,
            module=str(payload.get("logger") or payload.get("module") or ""),
            message=str(payload.get("message") or ""),
            request_id=_optional_str(payload.get("requestId")),
            run_id=_optional_str(payload.get("runId")),
            exception=str(exception) if exception else None,
            raw=payload,
        )

    def _build_dev_event(
        self, line: str, rel_path: str, locator: _EventLocator
    ) -> DiagnosticsEvent | None:
        match = _DEV_LINE_PATTERN.match(line)
        if match is None:
            return None
        raw_ts, service, channel, content = match.groups()
        component = service.lower()
        if component not in _COMPONENTS:
            component = "launcher"
        try:
            timestamp_str = _utc_iso(datetime.fromisoformat(raw_ts.replace("Z", "+00:00")))
        except ValueError:
            timestamp_str = "1970-01-01T00:00:00+00:00"
        run_id = rel_path.split("/")[1] if "/" in rel_path else None
        return DiagnosticsEvent(
            event_id=_encode_event_locator(
                _EventLocator(
                    file=rel_path,
                    line=locator.line,
                    offset=locator.offset,
                    timestamp=timestamp_str,
                )
            ),
            timestamp=timestamp_str,
            level="ERROR" if channel.lower() == "stderr" else "INFO",
            component=component,
            module=f"{service.lower()}.{channel.lower()}",
            message=content,
            request_id=None,
            run_id=run_id,
            exception=None,
            raw={"line": line},
        )

    def _detail_from_line(
        self,
        line: str,
        rel_path: str,
        line_no: int,
        *,
        locator: _EventLocator | None = None,
    ) -> dict[str, Any]:
        resolved_locator = locator or _EventLocator(file=rel_path, line=line_no)
        event = self._build_runtime_event(
            line, rel_path, resolved_locator
        ) or self._build_dev_event(line, rel_path, resolved_locator)
        if event is None:
            raise DiagnosticsNotFoundError(f"日志行无法解析：{rel_path}#{line_no}")
        return {
            "event": event,
            "raw": event.raw,
            "source": {"filePath": rel_path, "lineNumber": line_no},
        }

    def _summarize_run(self, run_dir: Path) -> RunSummary:
        files: list[RunFileInfo] = []
        total = 0
        for name in _ALL_RUN_FILES:
            path = run_dir / name
            if not path.is_file():
                continue
            stat = path.stat()
            total += stat.st_size
            files.append(
                RunFileInfo(
                    name=name,
                    size_bytes=stat.st_size,
                    modified_at=_utc_iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
                )
            )
        return RunSummary(
            run_id=run_dir.name,
            started_at=_run_started_at(run_dir.name),
            files=files,
            total_bytes=total,
        )


# ── 过滤与游标边界 ──────────────────────────────────────────────────────────


class _EventMatcher:
    """事件过滤器；定位失效的游标按时间戳降级过滤。"""

    def __init__(
        self,
        query: DiagnosticsQuery,
        cursor: _CursorPos | None,
        *,
        cursor_exact: bool,
    ) -> None:
        self.min_level = _LEVEL_ORDER.get(query.level.upper()) if query.level else None
        self.keyword = query.keyword.lower() if query.keyword else None
        self.request_id = query.request_id or None
        self.time_from = _to_iso(query.time_from) if query.time_from else None
        self.time_to = _to_iso(query.time_to) if query.time_to else None
        self.cursor = cursor
        self.cursor_exact = cursor_exact

    def match(self, event: DiagnosticsEvent) -> bool:
        if (
            self.cursor is not None
            and not self.cursor_exact
            and event.timestamp >= self.cursor.timestamp
        ):
            # 游标位置丢失（文件轮转）后的兜底：只保留严格更旧的事件。
            return False
        if self.time_from and event.timestamp < self.time_from:
            return False
        if self.time_to and event.timestamp > self.time_to:
            return False
        if self.min_level is not None:
            event_level = _LEVEL_ORDER.get(event.level.upper())
            if event_level is None or event_level < self.min_level:
                return False
        if self.request_id and event.request_id != self.request_id:
            return False
        if self.keyword:
            haystack = f"{event.message}\n{event.module}\n{event.exception or ''}".lower()
            if self.keyword not in haystack:
                return False
        return True


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _component_from_runtime_path(rel_path: str, payload: dict[str, Any]) -> str:
    """从 runtime 相对路径或 payload.component/service 推断诊断组件名。"""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "runtime":
        folder = parts[1].lower()
        if folder in _RUNTIME_COMPONENT_DIRS:
            return _RUNTIME_COMPONENT_DIRS[folder]
    explicit = _optional_str(payload.get("component"))
    if explicit:
        lowered = explicit.lower()
        if lowered in _COMPONENTS:
            return lowered
        if lowered in {"argus-web", "web", "frontend"}:
            return "web"
        if lowered in {"argus-java", "java"}:
            return "java"
        if lowered in {"argus-python", "python"}:
            return "python"
        if lowered in {"argus-system", "system"}:
            return "system"
    service = (_optional_str(payload.get("service")) or "").lower()
    if "java" in service:
        return "java"
    if "web" in service or "frontend" in service:
        return "web"
    if "system" in service:
        return "system"
    return "python"


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat()


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _run_started_at(run_id: str) -> str:
    try:
        dt = datetime.strptime(run_id, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
        return _utc_iso(dt)
    except ValueError:
        return ""
