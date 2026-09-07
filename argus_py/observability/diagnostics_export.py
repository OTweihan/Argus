"""诊断日志导出与实例诊断包构建。

对应 ``docs/optimizations/diagnostics-center-plan.md`` §17.11 / §17.12。

设计约束：
- 同步构建，由路由层经诊断并发闸门 + ``run_in_thread`` 调用；
- 有界：事件条数上限、内容字节预算、复用 store 扫描预算；
- 脱敏：消息 / 异常文本走 ``redact_sensitive_text``；
- 临时 zip 使用 ``DIAGNOSTICS_BUNDLE_TMP_PREFIX``；构建失败即 unlink；
- 诊断包元数据仅进程内登记，重启即失效（API 语义写明）。
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterator
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
    """按过滤条件有界采集事件（新→旧，截断时 truncated=True）。

    levels 与检索一致：取最低级别门槛（min-level），不再做精确集合过滤。
    跨 component 按与 store 相同的稳定键 k-way 归并，全局取最新 max_events 条（D-02）。
    同戳次序与 store 一致：timestamp DESC → file DESC → offset DESC。
    truncated 仅在确认仍有未导出匹配项时为 True（D-06 peek）；预算耗尽走 scan_limited。
    ``scan_budget`` 跨分页累计扫描字节并支持协作取消（D-01）。
    """
    component_filters: list[str | None] = list(components) if components else [None]
    level_floor = _level_floor(levels)
    kw = (keyword or "").strip() or None

    def _stream(component: str | None) -> Iterator[tuple[DiagnosticsEvent, bool]]:
        return _iter_component_events(
            store,
            component=component,
            time_from=time_from,
            time_to=time_to,
            level_floor=level_floor,
            keyword=kw,
            request_id=request_id,
            run_id=run_id,
            scan_budget=scan_budget,
        )

    # 统一 k-way 归并（单组件也是 1 路），按与 store 相同的稳定键取最新 N 条。
    # D-06：满额后再确认是否仍有 head，而非「凑满即 truncated」。
    heads: list[tuple[DiagnosticsEvent, bool, Iterator[tuple[DiagnosticsEvent, bool]]] | None] = []
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

    collected: list[DiagnosticsEvent] = []
    seen_ids: set[str] = set()
    while len(collected) < max_events:
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
            collected.append(event)

        try:
            nxt, nxt_lim = next(it)
            if nxt_lim:
                scan_limited = True
            heads[best_i] = (nxt, nxt_lim, it)
        except StopIteration:
            heads[best_i] = None

    # 满额且仍有未归并 head → 确认条数截断；否则仅 scan_limited 可能为 True。
    truncated = len(collected) >= max_events and any(h is not None for h in heads)
    return collected, truncated, scan_limited


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
    events, truncated, scan_limited = _collect_events(
        store,
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
    if scan_budget is not None and scan_budget.limited:
        scan_limited = True

    tmp, tmp_path = _open_temp_zip()
    total_size = 0
    size_truncated = False
    written = 0

    def _allow(nbytes: int) -> bool:
        nonlocal total_size, size_truncated
        if total_size + nbytes > _CONTENT_MAX_BYTES:
            size_truncated = True
            return False
        total_size += nbytes
        return True

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            lines: list[str] = []
            for event in events:
                line = json.dumps(_redact_event_wire(event), ensure_ascii=False)
                encoded = (line + "\n").encode("utf-8")
                if not _allow(len(encoded)):
                    break
                lines.append(line)
                written += 1
            ndjson = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
            zf.writestr("logs.ndjson", ndjson)

            manifest = {
                "kind": "diagnostics-log-export",
                "createdAt": _iso_now(),
                "eventCount": written,
                "requestedMaxEvents": limit,
                "truncated": truncated or size_truncated or written < len(events),
                "scanLimited": scan_limited,
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
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr("manifest.json", manifest_bytes)
    except Exception:
        # Windows：先关句柄再 unlink，否则 WinError 32。
        try:
            tmp.close()
        except OSError:
            pass
        _unlink_quiet(tmp_path)
        raise
    else:
        try:
            tmp.close()
        except OSError:
            pass

    return ExportResult(
        path=tmp_path,
        event_count=written,
        truncated=truncated or size_truncated,
        scan_limited=scan_limited,
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
    events, truncated, scan_limited = _collect_events(
        store,
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
    if scan_budget is not None and scan_budget.limited:
        scan_limited = True

    overview = service.overview_sync()
    system_info = service.system_info() if include_system_info else None

    tmp, tmp_path = _open_temp_zip()
    total_size = 0
    size_truncated = False
    written = 0
    contents: list[str] = []

    def _allow(nbytes: int) -> bool:
        nonlocal total_size, size_truncated
        if total_size + nbytes > _CONTENT_MAX_BYTES:
            size_truncated = True
            return False
        total_size += nbytes
        return True

    def _write_json(zf: zipfile.ZipFile, name: str, payload: Any) -> bool:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if not _allow(len(data)):
            return False
        zf.writestr(name, data)
        contents.append(name)
        return True

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            _write_json(zf, "overview.json", overview)
            if system_info is not None:
                _write_json(zf, "system.json", system_info)

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
                    _write_json(zf, "system-events.json", redacted_recent)
                except Exception:  # noqa: BLE001
                    logger.debug("诊断包写入系统事件失败", exc_info=True)

            lines: list[str] = []
            for event in events:
                line = json.dumps(_redact_event_wire(event), ensure_ascii=False)
                encoded = (line + "\n").encode("utf-8")
                if not _allow(len(encoded)):
                    break
                lines.append(line)
                written += 1
            ndjson = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
            # 固定结构：即使 0 条也写空 logs.ndjson
            zf.writestr("logs.ndjson", ndjson)
            contents.append("logs.ndjson")

            # 实际写入清单（manifest 自身稍后追加）
            actual_contents = ["manifest.json", *contents]
            manifest = {
                "kind": "diagnostics-bundle",
                "createdAt": _iso_now(),
                "eventCount": written,
                "requestedMaxEvents": limit,
                "truncated": truncated or size_truncated or written < len(events),
                "scanLimited": scan_limited,
                "contentBudgetBytes": _CONTENT_MAX_BYTES,
                "ttlSeconds": registry.ttl_seconds,
                "notes": [
                    "javaStatus may be omitted (overview_sync; no async Java probe)",
                    "level filter uses min-level semantics (same as log search)",
                ],
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
                "contents": actual_contents,
            }
            # manifest 尽量写入
            data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr("manifest.json", data)
    except Exception:
        try:
            tmp.close()
        except OSError:
            pass
        _unlink_quiet(tmp_path)
        raise
    else:
        try:
            tmp.close()
        except OSError:
            pass

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
        truncated=truncated or size_truncated,
        scan_limited=scan_limited,
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
