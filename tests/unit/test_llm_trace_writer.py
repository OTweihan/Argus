"""LLM trace 后台 writer + 启动期清理单测。

覆盖点：
- ``LLMTraceWriter.enqueue`` 单条 / 批量写入正确落盘
- ``stop`` 时 flush 残留记录，不丢条目
- 队列满时返回 ``False`` 且 ``dropped_count`` 累加
- ``cleanup_old_traces`` 按 TTL 删旧文件、按总量裁剪从最旧开始
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from argus_py.observability.llm_trace import LLMTraceRecord
from argus_py.observability.llm_trace_writer import (
    LLMTraceWriter,
    cleanup_old_traces,
)


def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


class TestLLMTraceWriter:
    """LLMTraceWriter 批量写入与生命周期。"""

    def test_enqueue_writes_to_file(self, tmp_path: Path) -> None:
        """enqueue 多条记录后 stop 应全部落盘。"""
        writer = LLMTraceWriter(max_queue_size=100, flush_interval_seconds=0.05)
        writer.start()
        target = tmp_path / "trace.jsonl"
        for i in range(5):
            assert writer.enqueue(target, LLMTraceRecord(trace_id=f"trc-{i}")) is True
        writer.stop(timeout=2.0)
        records = _read_jsonl(target)
        assert [r["trace_id"] for r in records] == [f"trc-{i}" for i in range(5)]
        assert writer.written_count == 5

    def test_batch_threshold_flush(self, tmp_path: Path) -> None:
        """单文件累计 32 条达到阈值时应立即 flush；stop 拿到剩余记录。"""
        writer = LLMTraceWriter(max_queue_size=1000, flush_interval_seconds=5.0)
        writer.start()
        target = tmp_path / "trace.jsonl"
        for i in range(40):
            writer.enqueue(target, LLMTraceRecord(trace_id=f"trc-{i}", task_id=f"t{i}"))
        # 等阈值触发的批量 flush 落盘
        time.sleep(0.2)
        writer.stop(timeout=2.0)
        records = _read_jsonl(target)
        assert len(records) == 40

    def test_queue_full_drops_records(self, tmp_path: Path) -> None:
        """队列满时应返回 False 并累加 dropped_count，不阻塞调用方。"""
        writer = LLMTraceWriter(max_queue_size=2)
        target = tmp_path / "trace.jsonl"
        rec = LLMTraceRecord()
        assert writer.enqueue(target, rec) is True
        assert writer.enqueue(target, rec) is True
        assert writer.enqueue(target, rec) is False
        assert writer.dropped_count == 1

    def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        writer = LLMTraceWriter(max_queue_size=10)
        writer.start()
        writer.stop(timeout=1.0)
        # 第二次 stop 不应抛
        writer.stop(timeout=1.0)

    def test_start_is_idempotent(self) -> None:
        writer = LLMTraceWriter(max_queue_size=10)
        writer.start()
        writer.start()
        writer.stop(timeout=1.0)


class TestCleanupOldTraces:
    """启动期清理：TTL + 总量裁剪。"""

    def _make_trace(self, path: Path, size_bytes: int, age_seconds: float) -> None:
        """生成指定大小和 mtime 的 trace 文件。"""
        path.write_bytes(b"x" * size_bytes)
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))

    def test_ttl_removes_old_files(self, tmp_path: Path) -> None:
        """retention_days=1 时，2 天前的文件应被删除，今天的保留。"""
        old = tmp_path / "old.jsonl"
        fresh = tmp_path / "fresh.jsonl"
        self._make_trace(old, 100, age_seconds=2 * 86400 + 60)
        self._make_trace(fresh, 100, age_seconds=60)

        summary = cleanup_old_traces(tmp_path, retention_days=1, total_size_mb=0)

        assert summary["deleted_ttl"] == 1
        assert summary["deleted_quota"] == 0
        assert not old.exists()
        assert fresh.exists()

    def test_quota_removes_oldest_first(self, tmp_path: Path) -> None:
        """总量超额时按 mtime 升序裁剪：最旧的先删。"""
        # 三个 0.5MB 文件，总量 1.5MB，预算 1MB → 应删一个最旧的
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        c = tmp_path / "c.jsonl"
        half_mb = 512 * 1024
        self._make_trace(a, half_mb, age_seconds=3 * 3600)
        self._make_trace(b, half_mb, age_seconds=2 * 3600)
        self._make_trace(c, half_mb, age_seconds=1 * 3600)

        summary = cleanup_old_traces(tmp_path, retention_days=0, total_size_mb=1)

        assert summary["deleted_ttl"] == 0
        assert summary["deleted_quota"] == 1
        # 最旧的 a 应被清掉
        assert not a.exists()
        assert b.exists()
        assert c.exists()

    def test_missing_dir_is_noop(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        summary = cleanup_old_traces(missing, retention_days=7, total_size_mb=500)
        assert summary == {
            "deleted_ttl": 0,
            "deleted_quota": 0,
            "remaining_files": 0,
            "remaining_size_mb": 0,
        }

    def test_disabled_thresholds_skip_cleanup(self, tmp_path: Path) -> None:
        """retention_days=0 且 total_size_mb=0 时不删任何文件。"""
        f = tmp_path / "t.jsonl"
        self._make_trace(f, 100, age_seconds=30 * 86400)
        summary = cleanup_old_traces(tmp_path, retention_days=0, total_size_mb=0)
        assert summary["deleted_ttl"] == 0
        assert summary["deleted_quota"] == 0
        assert f.exists()


class TestWriteTraceFallback:
    """write_trace 在 writer 未启动时应同步 fallback 写入。"""

    async def test_sync_fallback_when_writer_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无 writer 时直接 append 文件，行为与旧实现一致。"""
        from argus_py.observability import llm_trace

        # 不启动 writer，并把 OUTPUT_DIR 重定向到临时目录
        monkeypatch.setattr(llm_trace, "OUTPUT_DIR", tmp_path)
        # 强制重新加载配置：开启 trace、关闭脱敏便于断言
        llm_trace.reset_config_for_tests()
        monkeypatch.setenv("LLM_TRACE_ENABLED", "1")
        monkeypatch.setenv("LLM_TRACE_CONTENT_REDACT", "0")

        record = llm_trace.LLMTraceRecord(
            trace_id="trc-1",
            task_id="task-fallback",
            phase="planner",
            event=llm_trace.EVENT_LLM_STARTED,
        )
        await llm_trace.write_trace(record)
        # reset 一次，下个测试拿到干净状态
        llm_trace.reset_config_for_tests()

        out = tmp_path / "traces" / "task-fallback.jsonl"
        assert out.exists()
        records = _read_jsonl(out)
        assert records[0]["trace_id"] == "trc-1"
        assert records[0]["phase"] == "planner"
