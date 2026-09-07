"""诊断日志导出与实例诊断包构建。

对应 ``docs/optimizations/diagnostics-center-plan.md`` §17.11 / §17.12。

设计约束：
- 同步构建，由路由层经诊断并发闸门 + ``run_in_thread`` 调用；
- 有界：事件条数上限、内容字节预算、复用 store 扫描预算；
- 脱敏：消息 / 异常文本走 ``redact_sensitive_text``；
- 临时 zip 使用 ``DIAGNOSTICS_BUNDLE_TMP_PREFIX``；构建失败即 unlink；
- 诊断包元数据仅进程内登记，重启即失效（API 语义写明）；
- D-05：``_EventMergeStream`` 边 k-way 归并边写 NDJSON，避免预堆 max_events 列表；
  store 侧仍可能按扫描窗物化行（文件内 ts 可回退，不能只读 tail limit 行）。
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argus_py.core.ids import generate_id
from argus_py.infra.temp_cleanup import DIAGNOSTICS_BUNDLE_TMP_PREFIX
from argus_py.observability.diagnostics_service import DiagnosticsService
from argus_py.observability.diagnostics_store import (
    LEVEL_ORDER,
    DiagnosticsEvent,
    DiagnosticsQuery,
    DiagnosticsScanBudget,
    FileDiagnosticsLogStore,
    event_sort_key,
)
from argus_py.redaction import redact_sensitive_text

logger = logging.getLogger(__name__)

# 导出 / 诊断包硬上限（与单 worker 资源隔离对齐）
_DEFAULT_MAX_EVENTS = 2000
_HARD_MAX_EVENTS = 5000
# 写入 zip 前的内容字节预算（未压缩 NDJSON/JSON），防止无界膨胀。
_CONTENT_MAX_BYTES = 50 * 1024 * 1024
_BUNDLE_TTL_SECONDS = 15 * 60
# 进程内诊断包默认容量（条目数 / 总字节）；可被构造参数覆盖。
_DEFAULT_BUNDLE_MAX_ITEMS = 16
_DEFAULT_BUNDLE_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_PAGE_CHUNK = 200


class BundleCapacityError(RuntimeError):
    """诊断包登记容量已满（D-03）。"""


@dataclass(frozen=True)
class ExportResult:
    """导出结果：临时 zip 路径 + 元数据（写入 manifest.json）。"""

    path: str
    event_count: int
    truncated: bool
    scan_limited: bool
    components: list[str]
    levels: list[str]


@dataclass
class BundleRecord:
    """进程内诊断包登记项。"""

    bundle_id: str
    path: str
    created_at: float
    expires_at: float
    event_count: int
    truncated: bool
    scan_limited: bool
    size_bytes: int


@dataclass
class DiagnosticsBundleRegistry:
    """进程内诊断包登记表（非持久化，D-03）。

    - TTL + 条目数/总字节容量准入；
    - 锁内只改元数据，磁盘 unlink 在锁外执行（避免持锁 IO / 阻塞事件循环）；
    - 下载 ``claim`` 一次性领取；``purge_expired`` 供 lifespan 定时回收；
    - 删除失败路径进入重试队列，下次 purge 再试。
    重启后全部失效。
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _items: dict[str, BundleRecord] = field(default_factory=dict)
    _pending_unlink: list[str] = field(default_factory=list)
    ttl_seconds: int = _BUNDLE_TTL_SECONDS
    max_items: int = _DEFAULT_BUNDLE_MAX_ITEMS
    max_total_bytes: int = _DEFAULT_BUNDLE_MAX_TOTAL_BYTES

    def put(self, record: BundleRecord) -> None:
        """登记诊断包；容量不足时抛 ``BundleCapacityError``（调用方负责删文件）。

        容量拒绝前若已摘掉过期项，仍必须在锁外删除其文件，避免元数据与磁盘泄漏。
        """
        to_unlink: list[str] = []
        capacity_error: BundleCapacityError | None = None
        with self._lock:
            to_unlink.extend(self._purge_locked(time.time()))
            if record.bundle_id not in self._items:
                if len(self._items) >= self.max_items:
                    capacity_error = BundleCapacityError(
                        f"诊断包数量已达上限（{self.max_items}），请先下载或等待过期回收。"
                    )
                else:
                    total = sum(item.size_bytes for item in self._items.values())
                    if total + max(0, record.size_bytes) > self.max_total_bytes:
                        capacity_error = BundleCapacityError(
                            f"诊断包总大小已达上限（{self.max_total_bytes} 字节），"
                            "请先下载或等待过期回收。"
                        )
            if capacity_error is None:
                self._items[record.bundle_id] = record
        # 无论 put 成败，过期 purge 路径都要落盘清理。
        self._unlink_paths(to_unlink)
        if capacity_error is not None:
            raise capacity_error

    def get(self, bundle_id: str) -> BundleRecord | None:
        """只读查看；过期项仅注销元数据，文件在锁外删除。"""
        now = time.time()
        to_unlink: list[str] = []
        with self._lock:
            to_unlink.extend(self._purge_locked(now))
            record = self._items.get(bundle_id)
            if record is None:
                result = None
            elif record.expires_at <= now:
                dropped = self._items.pop(bundle_id, None)
                if dropped is not None:
                    to_unlink.append(dropped.path)
                result = None
            else:
                result = record
        self._unlink_paths(to_unlink)
        return result

    def claim(self, bundle_id: str, *, purge_expired: bool = True) -> BundleRecord | None:
        """一次性领取：取出并注销，避免并发双下。

        ``purge_expired=False`` 时只 pop 目标项（下载热路径），过期包交给定时
        ``purge_expired()``，避免在 asyncio 事件循环线程同步批量 unlink。
        """
        now = time.time()
        to_unlink: list[str] = []
        with self._lock:
            if purge_expired:
                to_unlink.extend(self._purge_locked(now))
            record = self._items.pop(bundle_id, None)
            if record is None:
                result = None
            elif record.expires_at <= now:
                to_unlink.append(record.path)
                result = None
            else:
                result = record
        self._unlink_paths(to_unlink)
        return result

    def pop(self, bundle_id: str) -> BundleRecord | None:
        """兼容旧名：仅 pop 元数据（不校验 TTL，不自动删文件）。"""
        with self._lock:
            return self._items.pop(bundle_id, None)

    def stats(self) -> dict[str, int]:
        """当前登记规模（测试 / 观测）。"""
        with self._lock:
            return {
                "items": len(self._items),
                "total_bytes": sum(item.size_bytes for item in self._items.values()),
                "pending_unlink": len(self._pending_unlink),
            }

    def purge_expired(self) -> int:
        """主动回收过期包与待重试删除；返回成功删除文件数。供定时任务调用。"""
        with self._lock:
            paths = self._purge_locked(time.time())
            paths.extend(self._pending_unlink)
            self._pending_unlink = []
        return self._unlink_paths(paths)

    def clear_all(self) -> int:
        """关闭时清空全部登记并尝试删文件；返回删除成功数。"""
        with self._lock:
            paths = [item.path for item in self._items.values()]
            paths.extend(self._pending_unlink)
            self._items.clear()
            self._pending_unlink = []
        return self._unlink_paths(paths)

    def _purge_locked(self, now: float) -> list[str]:
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        paths: list[str] = []
        for key in expired:
            record = self._items.pop(key, None)
            if record is not None:
                paths.append(record.path)
        return paths

    def _unlink_paths(self, paths: list[str]) -> int:
        removed = 0
        failed: list[str] = []
        for path in paths:
            try:
                target = Path(path)
                # missing_ok：文件已不在仍算清理成功，不进重试队列。
                target.unlink(missing_ok=True)
                removed += 1
            except OSError as exc:
                logger.warning("清理诊断包文件失败 %s: %s", path, exc)
                failed.append(path)
        if failed:
            with self._lock:
                # 去重，避免同一路径在失败重试队列里无限膨胀。
                pending = set(self._pending_unlink)
                for item in failed:
                    if item not in pending:
                        self._pending_unlink.append(item)
                        pending.add(item)
        return removed


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_event_wire(event: DiagnosticsEvent) -> dict[str, Any]:
    """事件 wire 字典脱敏（message / exception）。"""
    payload = event.to_wire()
    message = payload.get("message")
    if isinstance(message, str):
        payload["message"] = redact_sensitive_text(message)
    exception = payload.get("exception")
    if isinstance(exception, str):
        payload["exception"] = redact_sensitive_text(exception)
    return payload


def _normalize_components(components: list[str] | None) -> list[str]:
    if not components:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in components:
        name = str(item or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    return cleaned


def _normalize_levels(levels: list[str] | None) -> list[str]:
    if not levels:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in levels:
        name = str(item or "").strip().upper()
        if name == "WARNING":
            name = "WARN"
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    return cleaned


def _level_floor(levels: list[str]) -> str | None:
    """与日志检索一致：多级取数值最小者作为 store 最低级别门槛。"""
    if not levels:
        return None
    ordered = sorted(levels, key=lambda lv: LEVEL_ORDER.get(lv, 999))
    return ordered[0] if ordered else None


def _effective_max_events(max_events: int | None) -> int:
    if max_events is None:
        return _DEFAULT_MAX_EVENTS
    return max(1, min(int(max_events), _HARD_MAX_EVENTS))


def _iter_component_events(
    store: FileDiagnosticsLogStore,
    *,
    component: str | None,
    time_from: datetime | None,
    time_to: datetime | None,
    level_floor: str | None,
    keyword: str | None,
    request_id: str | None,
    run_id: str | None,
    scan_budget: DiagnosticsScanBudget | None = None,
) -> Iterator[tuple[DiagnosticsEvent, bool]]:
    """按 component 分页迭代事件（新→旧）。yield (event, scan_limited_seen)。"""
    cursor: str | None = None
    scan_limited = False
    while True:
        if scan_budget is not None and scan_budget.cancelled():
            scan_budget.mark_limited()
            return
        page = store.search(
            DiagnosticsQuery(
                time_from=time_from,
                time_to=time_to,
                component=component,
                level=level_floor,
                keyword=keyword,
                request_id=request_id,
                run_id=run_id,
                limit=_PAGE_CHUNK,
                cursor=cursor,
            ),
            scan_budget=scan_budget,
        )
        if page.scan_limited:
            scan_limited = True
        if not page.items and not page.has_more:
            return
        for event in page.items:
            yield event, scan_limited
        if not page.has_more or not page.next_cursor:
            return
        cursor = page.next_cursor


@dataclass
class _EventMergeStream:
    """k-way 归并事件流（D-02/D-05/D-06）：迭代产出事件，耗尽后可读截断标记。

    不预物化 ``max_events`` 全列表，写入端可边归并边写 ZIP，降低导出峰值内存。
    ``truncated`` / ``scan_limited`` 仅在迭代结束后有效。
    """

    store: FileDiagnosticsLogStore
    time_from: datetime | None
    time_to: datetime | None
    components: list[str]
    levels: list[str]
    keyword: str | None
    request_id: str | None
    run_id: str | None
    max_events: int
    scan_budget: DiagnosticsScanBudget | None = None
    truncated: bool = field(default=False, init=False)
    scan_limited: bool = field(default=False, init=False)
    _exhausted: bool = field(default=False, init=False)
    _iter_started: bool = field(default=False, init=False)
    _active_iter: Iterator[DiagnosticsEvent] | None = field(default=None, init=False)

    def __iter__(self) -> Iterator[DiagnosticsEvent]:
        """单次遍历：写入端提前 break 后可继续 drain 同一生成器以得到 D-06 标记。"""
        if self._active_iter is not None:
            return self._active_iter
        if self._iter_started:
            return iter(())
        self._iter_started = True
        self._active_iter = self._generate()
        return self._active_iter

    def drain(self) -> None:
        """若写入提前停止，耗尽剩余归并以确定 truncated / scan_limited。"""
        if self._exhausted:
            return
        for _ in self:
            pass

    def _generate(self) -> Iterator[DiagnosticsEvent]:
        component_filters: list[str | None] = list(self.components) if self.components else [None]
        level_floor = _level_floor(self.levels)
        kw = (self.keyword or "").strip() or None

        def _stream(component: str | None) -> Iterator[tuple[DiagnosticsEvent, bool]]:
            return _iter_component_events(
                self.store,
                component=component,
                time_from=self.time_from,
                time_to=self.time_to,
                level_floor=level_floor,
                keyword=kw,
                request_id=self.request_id,
                run_id=self.run_id,
                scan_budget=self.scan_budget,
            )

        heads: list[
            tuple[DiagnosticsEvent, bool, Iterator[tuple[DiagnosticsEvent, bool]]] | None
        ] = []
        scan_limited = False
        for component in component_filters:
            it = _stream(component)
            try:
                event, limited = next(it)
                if limited:
                    scan_limited = True
                heads.append((event, limited, it))
            except StopIteration:
                heads.append(None)

        yielded = 0
        seen_ids: set[str] = set()
        try:
            while yielded < self.max_events:
                best_i = -1
                best_key: tuple[str, str, int] | None = None
                for i, head in enumerate(heads):
                    if head is None:
                        continue
                    key = event_sort_key(head[0])
                    if best_key is None or key > best_key:
                        best_i = i
                        best_key = key
                if best_i < 0:
                    break

                event, limited, it = heads[best_i]  # type: ignore[misc]
                if limited:
                    scan_limited = True
                if event.event_id not in seen_ids:
                    seen_ids.add(event.event_id)
                    yielded += 1
                    yield event

                try:
                    nxt, nxt_lim = next(it)
                    if nxt_lim:
                        scan_limited = True
                    heads[best_i] = (nxt, nxt_lim, it)
                except StopIteration:
                    heads[best_i] = None
        finally:
            # 满额且仍有未归并 head → 确认条数截断；否则仅 scan_limited 可能为 True。
            # 若写入端提前 break 后 drain，finally 在真正耗尽时执行。
            self.truncated = yielded >= self.max_events and any(h is not None for h in heads)
            self.scan_limited = scan_limited
            self._exhausted = True


def _collect_events(
    store: FileDiagnosticsLogStore,
    *,
    time_from: datetime | None,
    time_to: datetime | None,
    components: list[str],
    levels: list[str],
    keyword: str | None,
    request_id: str | None,
    run_id: str | None,
    max_events: int,
    scan_budget: DiagnosticsScanBudget | None = None,
) -> tuple[list[DiagnosticsEvent], bool, bool]:
    """按过滤条件有界采集事件（新→旧）。兼容测试与需 list 的调用方。

    导出热路径优先用 ``_EventMergeStream`` 边归并边写，避免整表物化。
    """
    stream = _EventMergeStream(
        store=store,
        time_from=time_from,
        time_to=time_to,
        components=components,
        levels=levels,
        keyword=keyword,
        request_id=request_id,
        run_id=run_id,
        max_events=max_events,
        scan_budget=scan_budget,
    )
    items = list(stream)
    return items, stream.truncated, stream.scan_limited


def _manifest_contents(*member_names: str) -> list[str]:
    """manifest.contents：manifest.json 固定首位，其后为实际写入成员（去重保序）。"""
    ordered = ["manifest.json"]
    seen = {"manifest.json"}
    for name in member_names:
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _export_truncated(
    *,
    collect_truncated: bool,
    size_truncated: bool,
    member_truncated: bool,
) -> bool:
    """统一 truncated：采集确认更多 | 内容预算截断 | 成员未写全。"""
    return bool(collect_truncated or size_truncated or member_truncated)


def _open_temp_zip() -> tuple[Any, str]:
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        prefix=DIAGNOSTICS_BUNDLE_TMP_PREFIX,
        suffix=".zip",
    )
    return tmp, tmp.name


def _unlink_quiet(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("删除临时诊断文件失败 %s: %s", path, exc)


def _close_quiet(handle: Any) -> None:
    try:
        handle.close()
    except OSError:
        pass


# manifest 预留：写入其它成员前先从内容预算中扣减，保证成功 ZIP 必有 manifest（D-04）。
_MANIFEST_RESERVE_BYTES = 64 * 1024


class _ZipContentBudget:
    """ZIP 成员内容字节预算（未压缩），预留 manifest 空间。"""

    def __init__(self, max_bytes: int | None = None, reserve: int | None = None) -> None:
        # 运行时读取模块级常量，便于测试 monkeypatch。
        cap = _CONTENT_MAX_BYTES if max_bytes is None else max_bytes
        res = _MANIFEST_RESERVE_BYTES if reserve is None else reserve
        self.max_bytes = max(0, int(cap))
        self.reserve = max(0, min(int(res), self.max_bytes))
        self.used = 0
        self.size_truncated = False

    @property
    def remaining_for_members(self) -> int:
        return max(0, self.max_bytes - self.reserve - self.used)

    def try_consume(self, nbytes: int) -> bool:
        n = max(0, int(nbytes))
        if n > self.remaining_for_members:
            self.size_truncated = True
            return False
        self.used += n
        return True

    def write_manifest(self, zf: zipfile.ZipFile, payload: dict[str, Any]) -> None:
        """始终写入 manifest.json（可占用预留 + 剩余；超总上限则压缩 notes）。

        若缩略后仍超过剩余预算，仍硬写以保证 ZIP 必有 manifest，并标记
        ``manifestOverBudget=true``（可观测，不静默突破 contentBudgetBytes）。
        """
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        room = max(0, self.max_bytes - self.used)
        over_budget = False
        if len(data) > room:
            # 极端：缩略 notes / omitted 后仍写；若仍超则硬写（接受略超预算以保证真实性）
            slim = dict(payload)
            if isinstance(slim.get("notes"), list) and len(slim["notes"]) > 2:
                slim["notes"] = [*slim["notes"][:2], "…notes truncated for budget"]
            if isinstance(slim.get("omitted"), list) and len(slim["omitted"]) > 8:
                slim["omitted"] = slim["omitted"][:8]
                slim["omittedTruncated"] = True
            data = json.dumps(slim, ensure_ascii=False, indent=2).encode("utf-8")
            if len(data) > room:
                over_budget = True
                slim["manifestOverBudget"] = True
                notes = slim.get("notes")
                if isinstance(notes, list):
                    slim["notes"] = [
                        *notes,
                        "manifestOverBudget: wrote beyond contentBudgetBytes reserve",
                    ]
                else:
                    slim["notes"] = ["manifestOverBudget: wrote beyond contentBudgetBytes reserve"]
                data = json.dumps(slim, ensure_ascii=False, indent=2).encode("utf-8")
        zf.writestr("manifest.json", data)
        self.used += len(data)
        if over_budget:
            self.size_truncated = True


def _omitted_entry(path: str, reason: str, detail: str = "") -> dict[str, str]:
    """manifest.omitted 统一 schema：path + reason + 可选 detail。"""
    item = {"path": path, "reason": reason}
    if detail:
        item["detail"] = detail
    return item


def _write_ndjson_events(
    zf: zipfile.ZipFile,
    events: Iterable[DiagnosticsEvent],
    budget: _ZipContentBudget,
    *,
    member_name: str = "logs.ndjson",
) -> tuple[int, bool, bool]:
    """流式写入 NDJSON 成员（D-05）。

    返回 ``(written_count, size_hit_limit, member_created)``。
    成员仅在成功 ``ZipFile.open(..., "w")`` 后视为已创建（固定结构下即使 0 条也创建空文件）。
    """
    written = 0
    size_hit = False
    member_created = False
    with zf.open(member_name, "w") as raw:
        member_created = True
        for event in events:
            line = json.dumps(_redact_event_wire(event), ensure_ascii=False)
            encoded = (line + "\n").encode("utf-8")
            if not budget.try_consume(len(encoded)):
                size_hit = True
                break
            raw.write(encoded)
            written += 1
    return written, size_hit, member_created


def build_log_export(
    store: FileDiagnosticsLogStore,
    *,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    components: list[str] | None = None,
    levels: list[str] | None = None,
    keyword: str | None = None,
    request_id: str | None = None,
    run_id: str | None = None,
    max_events: int | None = None,
    scan_budget: DiagnosticsScanBudget | None = None,
) -> ExportResult:
    """构建日志导出 zip：manifest.json + logs.ndjson。

    构建失败时删除临时文件再抛出，避免泄漏 ``argus-diag-*.zip``。
    ``scan_budget`` 覆盖整次导出的累计扫描字节与协作取消（D-01）。
    """
    comps = _normalize_components(components)
    lvls = _normalize_levels(levels)
    limit = _effective_max_events(max_events)
    merge = _EventMergeStream(
        store=store,
        time_from=time_from,
        time_to=time_to,
        components=comps,
        levels=lvls,
        keyword=keyword,
        request_id=(request_id or None),
        run_id=(run_id or None),
        max_events=limit,
        scan_budget=scan_budget,
    )

    tmp, tmp_path = _open_temp_zip()
    budget = _ZipContentBudget()
    written = 0
    size_hit = False
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            # D-05：边 k-way 归并边写，不预堆 events 列表。
            written, size_hit, ndjson_created = _write_ndjson_events(zf, merge, budget)
            # size_hit 提前 break 时 drain 同一生成器，确定 D-06 truncated / scan_limited。
            merge.drain()
            if scan_budget is not None and scan_budget.limited:
                merge.scan_limited = True
            members: list[str] = []
            if ndjson_created:
                members.append("logs.ndjson")
            contents = _manifest_contents(*members)
            omitted: list[dict[str, str]] = []
            # size_hit → 成员未写完（流式下以 size_hit 为准）
            if size_hit:
                omitted.append(
                    _omitted_entry(
                        "logs.ndjson",
                        "content-budget",
                        f"wrote {written} events before content budget",
                    )
                )
            elif not ndjson_created:
                omitted.append(_omitted_entry("logs.ndjson", "write-failed"))
            manifest = {
                "kind": "diagnostics-log-export",
                "createdAt": _iso_now(),
                "eventCount": written,
                "requestedMaxEvents": limit,
                "truncated": _export_truncated(
                    collect_truncated=merge.truncated,
                    size_truncated=budget.size_truncated,
                    member_truncated=size_hit,
                ),
                "scanLimited": merge.scan_limited,
                "contentBudgetBytes": _CONTENT_MAX_BYTES,
                "filters": {
                    "from": time_from.isoformat() if time_from else None,
                    "to": time_to.isoformat() if time_to else None,
                    "components": comps or None,
                    "levels": lvls or None,
                    "keyword": keyword,
                    "requestId": request_id,
                    "runId": run_id,
                    "levelSemantics": "min-level",
                },
                "contents": contents,
            }
            if omitted:
                manifest["omitted"] = omitted
            budget.write_manifest(zf, manifest)
    except Exception:
        # Windows：先关句柄再 unlink，否则 WinError 32（D-04）。
        _close_quiet(tmp)
        _unlink_quiet(tmp_path)
        raise
    else:
        _close_quiet(tmp)

    return ExportResult(
        path=tmp_path,
        event_count=written,
        truncated=_export_truncated(
            collect_truncated=merge.truncated,
            size_truncated=budget.size_truncated,
            member_truncated=size_hit,
        ),
        scan_limited=merge.scan_limited or (scan_budget is not None and scan_budget.limited),
        components=comps,
        levels=lvls,
    )


def build_diagnostics_bundle(
    service: DiagnosticsService,
    store: FileDiagnosticsLogStore,
    registry: DiagnosticsBundleRegistry,
    *,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    components: list[str] | None = None,
    levels: list[str] | None = None,
    keyword: str | None = None,
    request_id: str | None = None,
    run_id: str | None = None,
    max_events: int | None = None,
    include_system_info: bool = True,
    include_recent_events: bool = True,
    scan_budget: DiagnosticsScanBudget | None = None,
) -> BundleRecord:
    """构建实例诊断包并登记到进程内 registry。

    构建失败时删除临时文件再抛出。容量拒绝时删除 zip 并抛 ``BundleCapacityError``。
    """
    comps = _normalize_components(components)
    lvls = _normalize_levels(levels)
    limit = _effective_max_events(max_events)
    merge = _EventMergeStream(
        store=store,
        time_from=time_from,
        time_to=time_to,
        components=comps,
        levels=lvls,
        keyword=keyword,
        request_id=(request_id or None),
        run_id=(run_id or None),
        max_events=limit,
        scan_budget=scan_budget,
    )

    overview = service.overview_sync()
    system_info = service.system_info() if include_system_info else None

    tmp, tmp_path = _open_temp_zip()
    budget = _ZipContentBudget()
    written = 0
    size_hit = False
    contents: list[str] = []
    omitted: list[dict[str, str]] = []
    notes: list[str] = [
        "javaStatus may be omitted (overview_sync; no async Java probe)",
        "level filter uses min-level semantics (same as log search)",
    ]

    def _write_json(zf: zipfile.ZipFile, name: str, payload: Any) -> bool:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if not budget.try_consume(len(data)):
            omitted.append(_omitted_entry(name, "content-budget"))
            return False
        zf.writestr(name, data)
        contents.append(name)
        return True

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            if not _write_json(zf, "overview.json", overview):
                notes.append("overview.json omitted due to content budget")
            if system_info is not None:
                if not _write_json(zf, "system.json", system_info):
                    notes.append("system.json omitted due to content budget")

            if include_recent_events:
                try:
                    recent = service.recent_system_events(limit=50)
                    redacted_recent = []
                    for item in recent:
                        msg = item.get("message")
                        if isinstance(msg, str):
                            item = {**item, "message": redact_sensitive_text(msg)}
                        exc = item.get("exception")
                        if isinstance(exc, str):
                            item = {**item, "exception": redact_sensitive_text(exc)}
                        redacted_recent.append(item)
                    if not _write_json(zf, "system-events.json", redacted_recent):
                        notes.append("system-events.json omitted due to content budget")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("诊断包读取系统事件失败", exc_info=True)
                    # D-04：包内可观察降级，而非仅 debug 日志
                    degradation = {
                        "ok": False,
                        "error": exc.__class__.__name__,
                        "message": str(exc)[:500],
                    }
                    if _write_json(zf, "system-events.json", degradation):
                        notes.append("system-events.json degraded: query failed")
                    else:
                        omitted.append(
                            _omitted_entry(
                                "system-events.json",
                                "query-failed+content-budget",
                                exc.__class__.__name__,
                            )
                        )
                        notes.append("system-events.json omitted after query failure")

            # 固定结构：即使 0 条也写空 logs.ndjson（边归并边写，D-05）
            written, size_hit, ndjson_created = _write_ndjson_events(zf, merge, budget)
            merge.drain()
            if scan_budget is not None and scan_budget.limited:
                merge.scan_limited = True
            if ndjson_created:
                contents.append("logs.ndjson")
            else:
                omitted.append(_omitted_entry("logs.ndjson", "write-failed"))
            if size_hit:
                omitted.append(
                    _omitted_entry(
                        "logs.ndjson",
                        "content-budget",
                        f"wrote {written} events before content budget",
                    )
                )

            manifest: dict[str, Any] = {
                "kind": "diagnostics-bundle",
                "createdAt": _iso_now(),
                "eventCount": written,
                "requestedMaxEvents": limit,
                "truncated": _export_truncated(
                    collect_truncated=merge.truncated,
                    size_truncated=budget.size_truncated,
                    member_truncated=size_hit,
                ),
                "scanLimited": merge.scan_limited,
                "contentBudgetBytes": _CONTENT_MAX_BYTES,
                "ttlSeconds": registry.ttl_seconds,
                "notes": notes,
                "filters": {
                    "from": time_from.isoformat() if time_from else None,
                    "to": time_to.isoformat() if time_to else None,
                    "components": comps or None,
                    "levels": lvls or None,
                    "keyword": keyword,
                    "requestId": request_id,
                    "runId": run_id,
                    "levelSemantics": "min-level",
                },
                "contents": _manifest_contents(*contents),
            }
            if omitted:
                manifest["omitted"] = omitted
            budget.write_manifest(zf, manifest)
    except Exception:
        _close_quiet(tmp)
        _unlink_quiet(tmp_path)
        raise
    else:
        _close_quiet(tmp)

    now = time.time()
    try:
        size_bytes = Path(tmp_path).stat().st_size
    except OSError:
        size_bytes = 0

    record = BundleRecord(
        bundle_id=generate_id("diag"),
        path=tmp_path,
        created_at=now,
        expires_at=now + registry.ttl_seconds,
        event_count=written,
        truncated=_export_truncated(
            collect_truncated=merge.truncated,
            size_truncated=budget.size_truncated,
            member_truncated=size_hit,
        ),
        scan_limited=merge.scan_limited or (scan_budget is not None and scan_budget.limited),
        size_bytes=size_bytes,
    )
    try:
        registry.put(record)
    except BundleCapacityError:
        _unlink_quiet(tmp_path)
        raise
    return record


__all__ = [
    "BundleCapacityError",
    "BundleRecord",
    "DiagnosticsBundleRegistry",
    "ExportResult",
    "build_diagnostics_bundle",
    "build_log_export",
]
