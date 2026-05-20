"""TraceIndex LRU 缓存行为测试：命中/失效/重建、并发安全（M1 修复后）。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from argus_py.observability.trace_index import (
    _TRACE_INDEX_CACHE,
    _TRACE_INDEX_CACHE_MAXSIZE,
    _cache_invalidate,
    _cache_put,
    _cached_load,
    _clear_cache,
)


class TestTraceIndexCache:
    def _populate(self, path: Path, entries: int = 3) -> dict[str, int]:
        data: list[dict[str, Any]] = [
            {"trace_id": f"trc-{i}", "offset": i * 100} for i in range(entries)
        ]
        offset_map: dict[str, int] = {}
        for entry in data:
            offset_map[entry["trace_id"]] = entry["offset"]
        _cache_put(path, data, offset_map)
        return offset_map

    def setup_method(self) -> None:
        _clear_cache()

    def test_cached_load_miss(self, tmp_path: Path) -> None:
        assert _cached_load(tmp_path / "no-such.jsonl") is None

    def test_cache_put_and_load_hit(self, tmp_path: Path) -> None:
        path = tmp_path / "test.jsonl"
        entries = [{"trace_id": "trc-1", "offset": 0}]
        offset_map = {"trc-1": 0}
        _cache_put(path, entries, offset_map)
        result = _cached_load(path)
        assert result is not None
        loaded_entries, loaded_map = result
        assert loaded_entries == entries
        assert loaded_map == offset_map

    def test_cache_invalidate_removes_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "test.jsonl"
        _cache_put(path, [{"trace_id": "trc-1", "offset": 0}], {"trc-1": 0})
        assert _cached_load(path) is not None
        _cache_invalidate(path)
        assert _cached_load(path) is None

    def test_cache_eviction(self, tmp_path: Path) -> None:
        """超过 MAXSIZE 时驱逐最旧条目。"""
        paths = []
        for i in range(_TRACE_INDEX_CACHE_MAXSIZE + 1):
            p = tmp_path / f"test-{i}.jsonl"
            _cache_put(p, [{"trace_id": f"trc-{i}", "offset": i}], {f"trc-{i}": i})
            paths.append(p)

        assert len(_TRACE_INDEX_CACHE) == _TRACE_INDEX_CACHE_MAXSIZE
        # 最旧的（i=0）应被驱逐
        assert _cached_load(paths[0]) is None
        # 最新的（i=MAXSIZE）应命中
        assert _cached_load(paths[-1]) is not None

    def test_cache_lru_move_to_end_on_hit(self, tmp_path: Path) -> None:
        """命中后条目移至末尾（LRU 语义）。"""
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        _cache_put(p1, [], {})
        _cache_put(p2, [], {})

        # 命中 p1 → p1 移至末尾
        _cached_load(p1)
        keys = list(_TRACE_INDEX_CACHE.keys())
        assert keys[-1] == p1.resolve()

    def test_clear_cache_empties_all(self, tmp_path: Path) -> None:
        _cache_put(tmp_path / "a.jsonl", [], {})
        _cache_put(tmp_path / "b.jsonl", [], {})
        _clear_cache()
        assert len(_TRACE_INDEX_CACHE) == 0

    def test_cache_put_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "test.jsonl"
        _cache_put(path, [{"trace_id": "old", "offset": 0}], {"old": 0})
        _cache_put(path, [{"trace_id": "new", "offset": 100}], {"new": 100})
        result = _cached_load(path)
        assert result is not None
        assert result[0][0]["trace_id"] == "new"


class TestTraceIndexConcurrent:
    def test_concurrent_cache_access(self, tmp_path: Path) -> None:
        """多线程读写缓存不崩溃（M1 修复验证）。"""
        _clear_cache()
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(thread_id: int) -> None:
            try:
                for i in range(50):
                    p = tmp_path / f"worker-{thread_id}-{i}.jsonl"
                    _cache_put(p, [{"trace_id": f"t-{i}", "offset": i}], {f"t-{i}": i})
                    _cached_load(p)
                    if i % 3 == 0:
                        _cache_invalidate(p)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(tid,), daemon=True) for tid in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"并发缓存访问异常：{errors}"
