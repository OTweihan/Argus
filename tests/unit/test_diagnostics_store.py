"""FileDiagnosticsLogStore 单元测试（诊断日志仓储，方案第 18 章）。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argus_py.observability.diagnostics_store import (
    DiagnosticsBadRequestError,
    DiagnosticsNotFoundError,
    DiagnosticsQuery,
    FileDiagnosticsLogStore,
)

RUN_ID = "20260826-120000"


def _runtime_line(
    ts: datetime,
    message: str,
    *,
    level: str = "INFO",
    logger: str = "argus_py.demo",
    request_id: str | None = None,
    exception: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "timestamp": ts.isoformat(),
        "level": level,
        "logger": logger,
        "message": message,
        "module": "demo",
        "function": "func",
        "line": 1,
    }
    if request_id:
        payload["requestId"] = request_id
    if exception:
        payload["exception"] = exception
    return json.dumps(payload, ensure_ascii=False)


def _dev_line(ts: datetime, service: str, channel: str, content: str) -> str:
    return f"{ts.isoformat().replace('+00:00', 'Z')} [{service}][{channel}] {content}"


@pytest.fixture
def logs_root(tmp_path: Path) -> Path:
    """构造 runtime JSONL + dev 会话目录的日志根。"""
    base = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
    runtime_dir = tmp_path / "runtime" / "python"
    runtime_dir.mkdir(parents=True)
    lines = [
        _runtime_line(base - timedelta(minutes=30), "oldest info"),
        _runtime_line(base - timedelta(minutes=20), "warn thing", level="WARNING"),
        _runtime_line(
            base - timedelta(minutes=10),
            "boom happened",
            level="ERROR",
            request_id="req_abc",
            exception="Traceback ...",
        ),
        "{broken json",  # 损坏行必须被跳过（方案 25.4）
        _runtime_line(base, "newest info", request_id="req_abc"),
    ]
    (runtime_dir / "argus.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    run_dir = tmp_path / "dev" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "python.log").write_text(
        "\n".join(
            [
                _dev_line(base - timedelta(minutes=5), "python", "stdout", "python booting"),
                _dev_line(base - timedelta(minutes=4), "python", "stderr", "python crashed"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "java.log").write_text(
        _dev_line(base - timedelta(minutes=3), "java", "stdout", "java started") + "\n",
        encoding="utf-8",
    )
    (run_dir / "frontend.log").write_text(
        _dev_line(base - timedelta(minutes=2), "frontend", "stdout", "vite ready") + "\n",
        encoding="utf-8",
    )
    (run_dir / "combined.log").write_text("combined superset\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(logs_root: Path) -> FileDiagnosticsLogStore:
    return FileDiagnosticsLogStore(logs_root)


class TestSearch:
    def test_newest_first_order(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery(limit=10))
        messages = [e.message for e in page.items]
        assert messages[0] == "newest info"
        assert messages[-1] == "oldest info"
        assert not page.has_more
        assert all(e.component == "python" for e in page.items)

    def test_limit_and_cursor_pagination(self, store: FileDiagnosticsLogStore) -> None:
        page1 = store.search(DiagnosticsQuery(limit=2))
        assert len(page1.items) == 2
        assert page1.has_more
        assert page1.next_cursor

        page2 = store.search(DiagnosticsQuery(limit=2, cursor=page1.next_cursor))
        ids1 = {e.event_id for e in page1.items}
        assert all(e.event_id not in ids1 for e in page2.items)
        assert [e.message for e in page2.items] == ["warn thing", "oldest info"]

    def test_missing_cursor_position_falls_back_to_timestamp(
        self,
        store: FileDiagnosticsLogStore,
        logs_root: Path,
    ) -> None:
        page1 = store.search(DiagnosticsQuery(limit=2))
        assert page1.next_cursor

        base = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
        runtime_log = logs_root / "runtime" / "python" / "argus.log"
        runtime_log.write_text(
            "\n".join(
                [
                    _runtime_line(base - timedelta(minutes=30), "oldest info"),
                    _runtime_line(base - timedelta(minutes=20), "warn thing", level="WARNING"),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        page2 = store.search(DiagnosticsQuery(limit=2, cursor=page1.next_cursor))

        assert [event.message for event in page2.items] == ["warn thing", "oldest info"]

    def test_legacy_line_cursor_remains_readable(
        self,
        store: FileDiagnosticsLogStore,
    ) -> None:
        from argus_py.observability.diagnostics_store import _b64_encode

        timestamp = datetime(2026, 8, 26, 11, 50, tzinfo=timezone.utc).isoformat()
        legacy_cursor = _b64_encode(
            json.dumps({"f": "runtime/python/argus.log", "l": 3, "t": timestamp})
        )

        page = store.search(DiagnosticsQuery(limit=2, cursor=legacy_cursor))

        assert [event.message for event in page.items] == ["warn thing", "oldest info"]

    def test_exact_cursor_remains_pageable_after_log_grows_beyond_budget(
        self,
        tmp_path: Path,
    ) -> None:
        runtime_dir = tmp_path / "runtime" / "python"
        runtime_dir.mkdir(parents=True)
        path = runtime_dir / "argus.log"
        base = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        path.write_text(
            "\n".join(
                [
                    _runtime_line(base - timedelta(seconds=2), "old"),
                    _runtime_line(base - timedelta(seconds=1), "middle"),
                    _runtime_line(base, "new"),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        store = FileDiagnosticsLogStore(tmp_path)
        store.set_scan_budget(1024 * 1024)
        page1 = store.search(DiagnosticsQuery(limit=1))
        assert page1.next_cursor

        with path.open("a", encoding="utf-8") as file:
            file.write("x" * (2 * 1024 * 1024) + "\n")

        page2 = store.search(DiagnosticsQuery(limit=1, cursor=page1.next_cursor))

        assert [event.message for event in page2.items] == ["middle"]
        assert page2.next_cursor

    def test_exact_cursor_skips_already_read_newer_files(self, tmp_path: Path) -> None:
        base = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        paths: list[Path] = []
        for index, hour in enumerate((10, 11, 12)):
            run_dir = tmp_path / "dev" / f"20260826-{hour:02d}0000"
            run_dir.mkdir(parents=True)
            path = run_dir / "java.log"
            path.write_text(
                _dev_line(
                    base + timedelta(hours=index),
                    "java",
                    "stdout",
                    f"event-{hour}",
                )
                + "\n",
                encoding="utf-8",
            )
            stamp = (base + timedelta(hours=index)).timestamp()
            os.utime(path, (stamp, stamp))
            paths.append(path)

        store = FileDiagnosticsLogStore(tmp_path)
        store.set_scan_budget(1024 * 1024)
        page1 = store.search(DiagnosticsQuery(component="java", limit=2))
        assert [event.message for event in page1.items] == ["event-12", "event-11"]
        assert page1.next_cursor

        with paths[-1].open("a", encoding="utf-8") as file:
            file.write("x" * (2 * 1024 * 1024) + "\n")

        page2 = store.search(DiagnosticsQuery(component="java", limit=2, cursor=page1.next_cursor))

        assert [event.message for event in page2.items] == ["event-10"]

    def test_level_filter_is_min_level(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery(level="ERROR"))
        assert [e.message for e in page.items] == ["boom happened"]

        warns = store.search(DiagnosticsQuery(level="WARN"))
        assert {e.message for e in warns.items} >= {"warn thing", "boom happened"}

    def test_keyword_case_insensitive(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery(keyword="BOOM"))
        assert [e.message for e in page.items] == ["boom happened"]

    def test_request_id_filter(self, store: FileDiagnosticsLogStore) -> None:
        events = store.search_by_request_id("req_abc")
        assert [e.message for e in events] == ["boom happened", "newest info"]

    def test_corrupt_lines_skipped(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery())
        assert all("{broken json" != e.message for e in page.items)

    def test_time_range_filter(self, store: FileDiagnosticsLogStore) -> None:
        start = datetime(2026, 8, 26, 11, 50, tzinfo=timezone.utc)
        page = store.search(DiagnosticsQuery(time_from=start))
        assert {e.message for e in page.items} == {"boom happened", "newest info"}


class TestJavaFrontendFromDevRuns:
    def test_component_java_scans_dev_runs(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery(component="java"))
        assert [e.message for e in page.items] == ["java started"]
        assert page.items[0].component == "java"
        assert page.items[0].run_id == RUN_ID

    def test_component_frontend(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery(component="frontend"))
        assert [e.message for e in page.items] == ["vite ready"]

    def test_stderr_dev_lines_marked_error(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search(DiagnosticsQuery(component="launcher", level="ERROR"))
        assert page.items == []

        errors = store.search_run_logs(RUN_ID, DiagnosticsQuery(component="python", level="ERROR"))
        assert [e.message for e in errors.items] == ["python crashed"]


class TestDetailAndContext:
    def test_detail_returns_raw_and_source(self, store: FileDiagnosticsLogStore) -> None:
        target = store.search(DiagnosticsQuery(level="ERROR")).items[0]
        detail = store.get_detail(target.event_id)
        assert detail["raw"]["level"] == "ERROR"
        assert detail["source"]["filePath"] == r"runtime/python/argus.log"
        assert detail["source"]["lineNumber"] == 3

    def test_legacy_line_event_id_remains_readable(self, store: FileDiagnosticsLogStore) -> None:
        from argus_py.observability.diagnostics_store import _encode_event_id

        legacy_id = _encode_event_id("runtime/python/argus.log", 3)
        detail = store.get_detail(legacy_id)

        assert detail["event"].message == "boom happened"
        assert detail["source"]["lineNumber"] == 3

    def test_context_same_file_window(self, store: FileDiagnosticsLogStore) -> None:
        target = store.search(DiagnosticsQuery(level="ERROR")).items[0]
        context = store.get_context(target.event_id, before=1, after=1)
        # 行 3 的前后各一条：损坏行被跳过后窗口内只剩可解析事件。
        messages = [e.message for e in context]
        assert "boom happened" in messages
        assert len(context) <= 3

    def test_detail_and_context_do_not_load_the_whole_file(
        self,
        store: FileDiagnosticsLogStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target = store.search(DiagnosticsQuery(level="ERROR")).items[0]

        def fail_read_text(*args: object, **kwargs: object) -> str:
            raise AssertionError("详情和上下文不应调用 Path.read_text")

        monkeypatch.setattr(Path, "read_text", fail_read_text)

        detail = store.get_detail(target.event_id)
        context = store.get_context(target.event_id, before=1, after=1)

        assert detail["event"].message == "boom happened"
        assert "boom happened" in [event.message for event in context]

    def test_invalid_event_id_raises_not_found(self, store: FileDiagnosticsLogStore) -> None:
        with pytest.raises(DiagnosticsNotFoundError):
            store.get_detail("not-a-valid-id")

    def test_traversal_event_id_rejected(
        self, store: FileDiagnosticsLogStore, tmp_path: Path
    ) -> None:
        secret = tmp_path.parent / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")
        rel_escape = "../secret.txt"
        from argus_py.observability.diagnostics_store import _encode_event_id

        forged = _encode_event_id(rel_escape, 1)
        with pytest.raises(DiagnosticsNotFoundError):
            store.get_detail(forged)


class TestRuns:
    def test_list_runs_desc(self, store: FileDiagnosticsLogStore, logs_root: Path) -> None:
        newer = logs_root / "dev" / "20260826-130000"
        newer.mkdir()
        (newer / "python.log").write_text("", encoding="utf-8")

        runs = store.list_runs()
        assert [r.run_id for r in runs] == ["20260826-130000", RUN_ID]
        first = runs[0]
        assert first.started_at.startswith("2026-08-26T13:00:00")
        assert first.total_bytes == 0

    def test_run_detail_files_exclude_nothing(self, store: FileDiagnosticsLogStore) -> None:
        run = store.get_run_detail(RUN_ID)
        names = {f.name for f in run.files}
        assert names == {"python.log", "java.log", "frontend.log", "combined.log"}
        assert run.total_bytes > 0

    def test_unknown_run_404(self, store: FileDiagnosticsLogStore) -> None:
        with pytest.raises(DiagnosticsNotFoundError):
            store.get_run_detail("20990101-000000")

    def test_invalid_run_id_rejected(self, store: FileDiagnosticsLogStore) -> None:
        with pytest.raises(DiagnosticsBadRequestError):
            store.get_run_detail("../../etc")

    def test_search_run_logs_scoped(self, store: FileDiagnosticsLogStore) -> None:
        page = store.search_run_logs(RUN_ID, DiagnosticsQuery(keyword="started"))
        messages = [e.message for e in page.items]
        assert messages == ["java started"]

    def test_search_run_logs_invalid_id(self, store: FileDiagnosticsLogStore) -> None:
        with pytest.raises(DiagnosticsBadRequestError):
            store.search_run_logs("bad-id!", DiagnosticsQuery())


class TestScanBudget:
    def test_scan_budget_exhaustion_flags_scan_limited(self, tmp_path: Path) -> None:
        """预算只够读两个候选时：第三个不扫描且 scanLimited=True（方案第 17 章）。

        独立构建日志根，避免共享夹具的额外数据源；mtime 显式设置，
        不依赖文件系统时间戳粒度。
        """
        filler = "x" * 700 * 1024
        for hour in (9, 10, 11):
            run_dir = tmp_path / "dev" / f"20260826-{hour:02d}0000"
            run_dir.mkdir(parents=True)
            path = run_dir / "java.log"
            path.write_text(
                filler
                + "\n"
                + _dev_line(
                    datetime(2026, 8, 26, hour, 0, tzinfo=timezone.utc),
                    "java",
                    "stdout",
                    "filler",
                )
                + "\n",
                encoding="utf-8",
            )
            stamp = datetime(2026, 8, 26, hour, 0, tzinfo=timezone.utc).timestamp()
            os.utime(path, (stamp, stamp))

        store = FileDiagnosticsLogStore(tmp_path)
        store.set_scan_budget(1024 * 1024)  # 1MB：一个完整文件 + 第二个文件尾部

        page = store.search(DiagnosticsQuery(component="java"))

        # 新→旧扫描：11 点完整读取、10 点只读取预算内尾部，9 点不再读取。
        assert page.scan_limited is True
        assert [e.run_id for e in page.items] == ["20260826-110000", "20260826-100000"]

    def test_single_oversized_file_reads_tail_within_budget(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "dev" / RUN_ID
        run_dir.mkdir(parents=True)
        path = run_dir / "java.log"
        base = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        path.write_text(
            "x" * (2 * 1024 * 1024)
            + "\n"
            + _dev_line(base - timedelta(seconds=1), "java", "stdout", "tail-old")
            + "\n"
            + _dev_line(base, "java", "stdout", "tail-new")
            + "\n",
            encoding="utf-8",
        )

        store = FileDiagnosticsLogStore(tmp_path)
        store.set_scan_budget(1024 * 1024)
        page = store.search(DiagnosticsQuery(component="java"))

        assert page.scan_limited is True
        assert [event.message for event in page.items] == ["tail-new", "tail-old"]
        detail = store.get_detail(page.items[0].event_id)
        assert detail["event"].message == "tail-new"


class TestEmptyRoot:
    def test_missing_dirs_return_empty(self, tmp_path: Path) -> None:
        store = FileDiagnosticsLogStore(tmp_path / "nonexistent" / "logs")
        assert store.search(DiagnosticsQuery()).items == []
        assert store.list_runs() == []
