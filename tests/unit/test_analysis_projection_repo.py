"""AnalysisRunRepository 投影写入批量化与游标分页计数修正单测。

覆盖 O-10：
- ``_write_projection`` 由逐行 ``execute`` 改为同事务分批 ``executemany``，
  单批内存受 ``_PROJECTION_BATCH_SIZE`` 约束；
- 中途失败整体回滚、重复投影幂等替换、超大批次全部落库；
- ``_paginated_query`` 仅首页计算 total，后续 cursor 页返回 None，
  且翻页无重复、无遗漏。
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from argus_py.analysis.enums import AnalysisRunStatus
from argus_py.analysis.models import AnalysisRun
from argus_py.infra.db import DbPool
from argus_py.task.models import Task
from argus_py.task.repositories.analysis_repo import (
    _PROJECTION_BATCH_SIZE,
    AnalysisRunRepository,
    _executemany_batched,
)
from argus_py.task.storage import TaskSQLiteStorage

# ── 投影数据构造 ──────────────────────────────────────────────────────────


def _call_nodes(aid: str, n: int, *, start: int = 0) -> list[dict[str, Any]]:
    return [
        {
            "call_node_id": f"{aid}:cn:{i}",
            "call_node_fingerprint": f"fp:cn:{i}",
            "class_name": f"com.example.C{i % 10}",
            "method_name": f"m{i}",
            "method_signature": None,
            "source_file": None,
            "source_start_line": None,
            "source_start_column": None,
            "source_end_line": None,
            "source_end_column": None,
        }
        for i in range(start, start + n)
    ]


def _endpoints(aid: str, n: int) -> list[dict[str, Any]]:
    return [
        {
            "endpoint_id": f"{aid}:ep:{i}",
            "endpoint_fingerprint": f"fp:ep:{i}",
            "http_method": "GET" if i % 2 == 0 else "POST",
            "raw_path": f"/api/item{i}",
            "normalized_exact_path": f"/api/item{i}",
            "normalized_path_template": f"/api/item{i}",
            "is_templated": False,
            "path_normalization_version": 1,
            "path_segment_count": 3,
            "static_prefix": None,
            "canonical_path_shape": None,
            "controller_class": f"Item{i}Controller",
            "controller_method": f"get{i}",
            "controller_method_signature": None,
            "parameters": [],
            "return_type": None,
            "source_file": None,
            "source_start_line": None,
            "source_start_column": None,
            "source_end_line": None,
            "source_end_column": None,
            "entry_call_node_id": None,
        }
        for i in range(n)
    ]


def _call_edges(aid: str, n: int) -> list[dict[str, Any]]:
    return [
        {
            "call_edge_id": f"{aid}:ce:{i}",
            "from_node_id": f"{aid}:cn:{i}",
            "to_node_id": f"{aid}:cn:{i + 1}",
            "to_class_name": "com.example.C",
            "to_method_name": "target",
            "resolution_type": "STATIC",
            "confidence": "HIGH",
            "source_file": None,
            "source_start_line": None,
            "source_start_column": None,
            "source_end_line": None,
            "source_end_column": None,
        }
        for i in range(n)
    ]


def _execution_flows(aid: str, n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flows: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for i in range(n):
        fid = f"{aid}:ef:{i}"
        flows.append(
            {
                "execution_flow_id": fid,
                "execution_flow_fingerprint": fid,
                "entry_point": f"/api/flow{i}",
                "call_depth": 3,
            }
        )
        for s in range(2):
            steps.append(
                {
                    "flow_step_id": f"fs:{fid}:{s}",
                    "execution_flow_id": fid,
                    "step_index": s,
                    "depth": s,
                    "method_key": f"com.example.F#s{s}",
                    "class_name": "com.example.F",
                    "method_name": f"s{s}",
                    "call_node_id": f"{aid}:cn:{s}",
                }
            )
    return flows, steps


def _clusters(aid: str, n: int) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": f"{aid}:cl:{i}",
            "suggested_label": f"cluster-{i}",
            "member_keys": [f"{aid}:cn:{i}"],
            "member_count": 1,
        }
        for i in range(n)
    ]


def _projection(
    aid: str,
    *,
    call_nodes: int = 0,
    endpoints: int = 0,
    call_edges: int = 0,
    flows: int = 0,
    clusters: int = 0,
) -> dict[str, Any]:
    flow_rows, step_rows = _execution_flows(aid, flows)
    return {
        "call_nodes": _call_nodes(aid, call_nodes),
        "endpoints": _endpoints(aid, endpoints),
        "call_edges": _call_edges(aid, call_edges),
        "execution_flows": flow_rows,
        "flow_steps": step_rows,
        "clusters": _clusters(aid, clusters),
        "diagnostics": {
            "total_source_files": 10,
            "eligible_source_files": 10,
            "parsed_file_count": 10,
            "failed_file_count": 0,
            "failed_files": [],
            "total_calls": call_edges,
            "resolved_high": call_edges,
            "resolved_medium": 0,
            "resolved_low": 0,
            "unresolved": 0,
            "classpath_available": True,
            "jar_count": 5,
            "classpath_source": "maven",
            "classpath_warnings": [],
            "classpath_errors": [],
            "module_count": 2,
            "application_module_count": 1,
        },
    }


# ── 夹具 ──────────────────────────────────────────────────────────────────


@pytest.fixture
def storage(tmp_path: Path) -> TaskSQLiteStorage:
    """临时数据库上的存储 facade（task / analysis repo 共享同一 DbPool）。"""
    return TaskSQLiteStorage(tmp_path / "projection.db")


def _create_run(storage: TaskSQLiteStorage, task_id: str, analysis_id: str) -> None:
    storage.save(Task(task_id=task_id, goal="白盒投影"))
    storage.create_analysis_run(
        AnalysisRun(
            analysis_id=analysis_id,
            task_id=task_id,
            source_snapshot_id="snap-1",
            run_status="RUNNING",
            external_job_id="job-1",
            result_schema_version=1,
            config_json="{}",
        )
    )


def _complete(
    storage: TaskSQLiteStorage,
    aid: str,
    proj: dict[str, Any],
    *,
    digest: str = "d1",
) -> None:
    storage.complete_analysis_projection(
        aid,
        completeness="COMPLETE",
        quality_issues_json="[]",
        result_digest=digest,
        projection_data=proj,
    )


# ── 分批写入 ──────────────────────────────────────────────────────────────


class _RecordingConn:
    """记录每次 executemany 传入行数的假连接。"""

    def __init__(self) -> None:
        self.calls: list[list[tuple]] = []

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        self.calls.append(list(rows))


def test_executemany_batched_chunks_by_batch_size() -> None:
    conn = _RecordingConn()
    rows = [("r", i) for i in range(_PROJECTION_BATCH_SIZE * 2 + 137)]
    _executemany_batched(conn, "INSERT ...", rows)
    assert [len(c) for c in conn.calls] == [500, 500, 137]
    flattened = [r for chunk in conn.calls for r in chunk]
    assert flattened == rows


def test_executemany_batched_streams_generator_in_bounded_batches() -> None:
    """生成器行源同样分片：每批不超过 batch_size，总量一致。"""
    conn = _RecordingConn()

    def gen() -> Any:
        for i in range(_PROJECTION_BATCH_SIZE * 2 + 7):
            yield ("r", i)

    _executemany_batched(conn, "INSERT ...", gen())
    assert [len(c) for c in conn.calls] == [500, 500, 7]
    assert len([r for chunk in conn.calls for r in chunk]) == _PROJECTION_BATCH_SIZE * 2 + 7


def test_executemany_batched_exact_multiple_splits_evenly() -> None:
    conn = _RecordingConn()
    _executemany_batched(conn, "sql", [("r", i) for i in range(1000)], batch_size=500)
    assert [len(c) for c in conn.calls] == [500, 500]


def test_executemany_batched_empty_rows_is_noop() -> None:
    conn = _RecordingConn()
    _executemany_batched(conn, "sql", [])
    assert conn.calls == []


class _ExecutemanyProbe:
    """记录 execute / executemany / DELETE 调用次数的假连接。"""

    def __init__(self) -> None:
        self.execute_calls = 0
        self.executemany_calls = 0
        self.delete_calls = 0

    def execute(self, sql: str, params: Any = None) -> None:  # noqa: ARG002
        stripped = sql.strip().upper()
        if stripped.startswith("DELETE"):
            self.delete_calls += 1
        else:
            self.execute_calls += 1

    def executemany(self, sql: str, rows: list[tuple]) -> None:  # noqa: ARG002
        self.executemany_calls += 1


def test_write_projection_uses_executemany_not_rowwise(tmp_path: Path) -> None:
    """投影写入走 executemany 分批，诊断仍为单行 execute。"""
    repo = AnalysisRunRepository(DbPool(tmp_path / "unused.db"))
    probe = _ExecutemanyProbe()
    aid = "a-probe"
    proj = _projection(aid, call_nodes=3, endpoints=2, call_edges=1, flows=2, clusters=1)
    repo._write_projection(probe, aid, proj)

    # 7 张投影表各一次 DELETE；6 张批量表各一次 executemany；diagnostics 单行 execute。
    assert probe.delete_calls == 7
    assert probe.executemany_calls == 6
    assert probe.execute_calls == 1


# ── 原子性与幂等 ──────────────────────────────────────────────────────────


def test_complete_projection_writes_all_tables(storage: TaskSQLiteStorage) -> None:
    aid = "a-full"
    _create_run(storage, "t-full", aid)
    proj = _projection(aid, call_nodes=5, endpoints=4, call_edges=3, flows=2, clusters=1)
    _complete(storage, aid, proj)

    run = storage.get_analysis_run(aid)
    assert run is not None
    assert run.run_status == AnalysisRunStatus.SUCCEEDED.value
    assert run.completeness_status == "COMPLETE"

    counts = storage.get_analysis_counts(aid)
    assert counts["analysis_call_nodes"] == 5
    assert counts["analysis_endpoints"] == 4
    assert counts["analysis_call_edges"] == 3
    assert counts["analysis_execution_flows"] == 2
    assert counts["analysis_clusters"] == 1

    # 行映射回读与行数一致
    nodes, _, total, _ = storage.list_analysis_call_nodes(aid, limit=100)
    assert total == 5
    assert len(nodes) == 5
    steps = storage.list_all_analysis_flow_steps(aid)
    assert len(steps) == 4  # 2 flows × 2 steps


def test_repeat_projection_replaces_not_duplicates(storage: TaskSQLiteStorage) -> None:
    aid = "a-rep"
    _create_run(storage, "t-rep", aid)
    _complete(storage, aid, _projection(aid, call_nodes=3, endpoints=2, call_edges=1))

    # 第二次投影数量与内容都变化，应整体替换而非追加
    _complete(storage, aid, _projection(aid, call_nodes=5, endpoints=6, call_edges=4))
    counts = storage.get_analysis_counts(aid)
    assert counts["analysis_call_nodes"] == 5
    assert counts["analysis_endpoints"] == 6
    assert counts["analysis_call_edges"] == 4

    nodes, _, total, _ = storage.list_analysis_call_nodes(aid, limit=100)
    assert total == 5
    assert {n["call_node_id"] for n in nodes} == {f"{aid}:cn:{i}" for i in range(5)}


def test_large_projection_all_rows_land(storage: TaskSQLiteStorage) -> None:
    """超大批次（跨多批）逐表全部落库，行数与输入一致。"""
    aid = "a-large"
    _create_run(storage, "t-large", aid)
    n = _PROJECTION_BATCH_SIZE * 2 + 137  # 1137，跨 3 批
    _complete(
        storage,
        aid,
        _projection(aid, call_nodes=n, endpoints=n, call_edges=n, flows=10, clusters=n),
    )

    counts = storage.get_analysis_counts(aid)
    assert counts["analysis_call_nodes"] == n
    assert counts["analysis_endpoints"] == n
    assert counts["analysis_call_edges"] == n
    assert counts["analysis_clusters"] == n
    assert counts["analysis_execution_flows"] == 10


def test_projection_failure_rolls_back_atomically(storage: TaskSQLiteStorage) -> None:
    """写入中途失败时，已提交的旧投影保持完整，不暴露半份新投影。"""
    aid = "a-rollback"
    _create_run(storage, "t-rollback", aid)
    _complete(storage, aid, _projection(aid, call_nodes=4, endpoints=4, call_edges=2))

    # 第二份投影注入重复 call_node_id（PRIMARY KEY 冲突），executemany 中途抛错
    bad = _projection(aid, call_nodes=2, endpoints=9, call_edges=3)
    bad["call_nodes"].append(dict(bad["call_nodes"][0]))
    with pytest.raises(sqlite3.IntegrityError):
        _complete(storage, aid, bad)

    # 事务整体回滚：仍是第一份投影的完整状态
    run = storage.get_analysis_run(aid)
    assert run is not None
    assert run.run_status == AnalysisRunStatus.SUCCEEDED.value
    counts = storage.get_analysis_counts(aid)
    assert counts["analysis_call_nodes"] == 4
    assert counts["analysis_endpoints"] == 4
    assert counts["analysis_call_edges"] == 2


def test_failed_projection_leaves_run_running(storage: TaskSQLiteStorage) -> None:
    """从未提交过投影的分析中途失败：run 保持 RUNNING，无任何半份投影。"""
    aid = "a-fresh-fail"
    _create_run(storage, "t-fresh-fail", aid)
    bad = _projection(aid, call_nodes=2, endpoints=2)
    bad["call_nodes"].append(dict(bad["call_nodes"][0]))
    with pytest.raises(sqlite3.IntegrityError):
        _complete(storage, aid, bad)

    run = storage.get_analysis_run(aid)
    assert run is not None
    assert run.run_status == "RUNNING"
    counts = storage.get_analysis_counts(aid)
    assert counts["analysis_call_nodes"] == 0
    assert counts["analysis_endpoints"] == 0


# ── 游标分页 ──────────────────────────────────────────────────────────────


def test_cursor_pagination_total_only_first_page(storage: TaskSQLiteStorage) -> None:
    """首页计算 total；后续 cursor 页不再执行 COUNT，翻页无重复、无遗漏。"""
    aid = "a-paging"
    _create_run(storage, "t-paging", aid)
    _complete(storage, aid, _projection(aid, endpoints=25))

    count_sql = 0

    def _trace(sql: str) -> None:
        nonlocal count_sql
        if sql.strip().upper().startswith("SELECT COUNT"):
            count_sql += 1

    original_new_conn = storage._tasks._pool._new_conn

    def traced_new_conn(read_only: bool):  # noqa: FBT001
        conn = original_new_conn(read_only)
        conn.set_trace_callback(_trace)
        return conn

    storage._tasks._pool._new_conn = traced_new_conn  # type: ignore[method-assign]
    try:
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(4):  # 25 条 / limit 10 → 至多 3 页，留 1 次容差
            items, cursor, total, has_more = storage.list_analysis_endpoints(
                aid, cursor=cursor, limit=10
            )
            if seen:
                assert total is None, "后续 cursor 页不应重复计算 total"
            else:
                assert total == 25
            seen.extend(ep["endpoint_id"] for ep in items)
            if not has_more:
                assert cursor is None
                break
    finally:
        storage._tasks._pool._new_conn = original_new_conn  # type: ignore[method-assign]

    # 全程只执行过 1 次 COUNT（首屏）
    assert count_sql == 1, f"后续页仍执行了 COUNT：{count_sql}"
    assert len(seen) == 25
    assert len(set(seen)) == 25  # 无重复


def test_cursor_pagination_exact_multiple_boundary(storage: TaskSQLiteStorage) -> None:
    """末页恰好填满 limit 时 has_more=False 且不再产生下一页游标。"""
    aid = "a-boundary"
    _create_run(storage, "t-boundary", aid)
    _complete(storage, aid, _projection(aid, endpoints=20))

    items, next_cursor, total, has_more = storage.list_analysis_endpoints(aid, limit=10)
    assert len(items) == 10
    assert total == 20
    assert has_more is True
    assert next_cursor is not None
    items2, next_cursor2, total2, has_more2 = storage.list_analysis_endpoints(
        aid, cursor=next_cursor, limit=10
    )
    assert len(items2) == 10
    assert total2 is None
    assert has_more2 is False
    assert next_cursor2 is None
    seen = [ep["endpoint_id"] for ep in items] + [ep["endpoint_id"] for ep in items2]
    assert len(set(seen)) == 20


def test_cursor_pagination_with_filter(storage: TaskSQLiteStorage) -> None:
    """带筛选条件（class_name LIKE）的游标分页同样无重复、无遗漏。"""
    aid = "a-filter"
    _create_run(storage, "t-filter", aid)
    nodes = [
        {
            "call_node_id": f"{aid}:cn:{i}",
            "call_node_fingerprint": f"fp:cn:{i}",
            "class_name": "com.example.Target",
            "method_name": f"m{i:02d}",
            "method_signature": None,
            "source_file": None,
            "source_start_line": None,
            "source_start_column": None,
            "source_end_line": None,
            "source_end_column": None,
        }
        for i in range(15)
    ]
    proj = _projection(aid)
    proj["call_nodes"] = nodes
    _complete(storage, aid, proj)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        items, cursor, total, has_more = storage.list_analysis_call_nodes(
            aid, class_name="Target", cursor=cursor, limit=6
        )
        if seen:
            assert total is None
        else:
            assert total == 15
        seen.extend(n["call_node_id"] for n in items)
        if not has_more:
            break
    assert len(seen) == 15
    assert len(set(seen)) == 15


def test_invalid_cursor_falls_back_to_first_page(storage: TaskSQLiteStorage) -> None:
    """无效游标回退首页：仍返回 total，且不抛异常。"""
    aid = "a-invalid"
    _create_run(storage, "t-invalid", aid)
    _complete(storage, aid, _projection(aid, endpoints=5))

    bad_cursor = base64.urlsafe_b64encode(b"not-valid-json").decode()
    items, next_cursor, total, has_more = storage.list_analysis_endpoints(
        aid, cursor=bad_cursor, limit=10
    )
    assert total == 5
    assert len(items) == 5
    assert has_more is False
    assert next_cursor is None


def _encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


@pytest.mark.parametrize(
    "bad_cursor",
    [
        _encode_cursor({"k": 5}),  # 键值非列表
        _encode_cursor({"k": "nope"}),  # 键值为字符串
        _encode_cursor({"k": [1]}),  # 键数与排序列数（3）不符
    ],
    ids=["non_list_keys", "string_keys", "wrong_key_count"],
)
def test_malformed_cursor_falls_back_to_first_page(
    storage: TaskSQLiteStorage, bad_cursor: str
) -> None:
    """能解码但结构非法的游标回退首页：不 500，仍返回 total 与首页数据。"""
    aid = "a-malformed"
    _create_run(storage, "t-malformed", aid)
    _complete(storage, aid, _projection(aid, endpoints=5))

    items, next_cursor, total, has_more = storage.list_analysis_endpoints(
        aid, cursor=bad_cursor, limit=10
    )
    assert total == 5
    assert len(items) == 5
    assert has_more is False
    assert next_cursor is None
