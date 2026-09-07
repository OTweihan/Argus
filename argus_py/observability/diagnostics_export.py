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
    FileDiagnosticsLogStore,
)
from argus_py.redaction import redact_sensitive_text

logger = logging.getLogger(__name__)

# 导出 / 诊断包硬上限（与单 worker 资源隔离对齐）
_DEFAULT_MAX_EVENTS = 2000
_HARD_MAX_EVENTS = 5000
# 写入 zip 前的内容字节预算（未压缩 NDJSON/JSON），防止无界膨胀。
_CONTENT_MAX_BYTES = 50 * 1024 * 1024
_BUNDLE_TTL_SECONDS = 15 * 60
_PAGE_CHUNK = 200


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
    """进程内诊断包登记表（非持久化）。

    单进程硬约束下足够；重启后全部失效。下载应 ``claim``（领取即注销），
    本表在 put/claim 时顺带做 TTL 回收。
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _items: dict[str, BundleRecord] = field(default_factory=dict)
    ttl_seconds: int = _BUNDLE_TTL_SECONDS

    def put(self, record: BundleRecord) -> None:
        with self._lock:
            self._purge_locked(time.time())
            self._items[record.bundle_id] = record

    def get(self, bundle_id: str) -> BundleRecord | None:
        """只读查看（不过期不删除登记）；过期项会清理文件。"""
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            record = self._items.get(bundle_id)
            if record is None:
                return None
            if record.expires_at <= now:
                self._drop_locked(bundle_id)
                return None
            return record

    def claim(self, bundle_id: str) -> BundleRecord | None:
        """一次性领取：取出并注销，避免并发双下。"""
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            record = self._items.pop(bundle_id, None)
            if record is None:
                return None
            if record.expires_at <= now:
                self._unlink_path(record.path)
                return None
            return record

    def pop(self, bundle_id: str) -> BundleRecord | None:
        """兼容旧名：等同 claim（不校验 TTL，仅 pop）。"""
        with self._lock:
            return self._items.pop(bundle_id, None)

    def _purge_locked(self, now: float) -> None:
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            self._drop_locked(key)

    def _drop_locked(self, bundle_id: str) -> None:
        record = self._items.pop(bundle_id, None)
        if record is None:
            return
        self._unlink_path(record.path)

    @staticmethod
    def _unlink_path(path: str) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("清理过期诊断包失败 %s: %s", path, exc)


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
) -> Iterator[tuple[DiagnosticsEvent, bool]]:
    """按 component 分页迭代事件（新→旧）。yield (event, scan_limited_seen)。"""
    cursor: str | None = None
    scan_limited = False
    while True:
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
            )
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
) -> tuple[list[DiagnosticsEvent], bool, bool]:
    """按过滤条件有界采集事件（新→旧，截断时 truncated=True）。

    levels 与检索一致：取最低级别门槛（min-level），不再做精确集合过滤。
    多 component 时按时间戳 k-way 归并，全局取最新 max_events 条（避免先占满）。
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
        )

    # 单组件：顺序取满即可
    if len(component_filters) == 1:
        collected: list[DiagnosticsEvent] = []
        scan_limited = False
        stream = _stream(component_filters[0])
        for event, limited in stream:
            if limited:
                scan_limited = True
            collected.append(event)
            if len(collected) >= max_events:
                # 再 peek 一条判断是否还有剩余
                try:
                    next(stream)
                    return collected, True, scan_limited
                except StopIteration:
                    return collected, False, scan_limited
        return collected, False, scan_limited

    # 多组件：k-way merge by ISO timestamp desc
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

    collected = []
    seen_ids: set[str] = set()
    while len(collected) < max_events:
        best_i = -1
        best_ts = ""
        for i, head in enumerate(heads):
            if head is None:
                continue
            event = head[0]
            ts = event.timestamp or ""
            if best_i < 0 or ts > best_ts:
                best_i = i
                best_ts = ts
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

        if len(collected) >= max_events:
            truncated = any(h is not None for h in heads)
            return collected, truncated, scan_limited

    return collected, False, scan_limited


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
) -> ExportResult:
    """构建日志导出 zip：manifest.json + logs.ndjson。

    构建失败时删除临时文件再抛出，避免泄漏 ``argus-diag-*.zip``。
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
    )

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
) -> BundleRecord:
    """构建实例诊断包并登记到进程内 registry。

    构建失败时删除临时文件再抛出。
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
    )

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
    registry.put(record)
    return record


__all__ = [
    "BundleRecord",
    "DiagnosticsBundleRegistry",
    "ExportResult",
    "build_diagnostics_bundle",
    "build_log_export",
]
