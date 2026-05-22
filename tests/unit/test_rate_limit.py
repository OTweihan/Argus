"""限流：TokenBucketLimiter、RateLimitRule、middleware 行为。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from argus_py.api.rate_limit import (
    RateLimitMiddleware,
    RateLimitRule,
    TokenBucketLimiter,
    build_rules,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestRateLimitRule:
    def test_exact_path_matches(self) -> None:
        rule = RateLimitRule(
            name="create_task",
            method="POST",
            path_pattern="/tasks",
            capacity=10,
            refill_per_sec=1.0,
        )
        assert rule.matches("POST", "/tasks")
        assert not rule.matches("POST", "/tasks/abc")
        assert not rule.matches("GET", "/tasks")

    def test_wildcard_single_segment(self) -> None:
        rule = RateLimitRule(
            name="start_task",
            method="POST",
            path_pattern="/tasks/*/start",
            capacity=10,
            refill_per_sec=1.0,
        )
        assert rule.matches("POST", "/tasks/abc/start")
        assert rule.matches("POST", "/tasks/123-uuid/start")
        # * 不能跨 segment
        assert not rule.matches("POST", "/tasks/a/b/start")
        # 不能裸前缀
        assert not rule.matches("POST", "/tasks/start")

    def test_method_case_insensitive(self) -> None:
        rule = RateLimitRule(
            name="x", method="post", path_pattern="/x", capacity=1, refill_per_sec=1
        )
        assert rule.matches("POST", "/x")
        assert rule.matches("post", "/x")


class TestTokenBucketLimiter:
    def test_initial_full_bucket_allows_burst(self) -> None:
        limiter = TokenBucketLimiter()
        # 容量 3：连续 3 次都过
        for _ in range(3):
            ok, _ = limiter.try_acquire(("c", "r"), capacity=3, refill_per_sec=1.0)
            assert ok
        # 第 4 次被拒
        ok, wait = limiter.try_acquire(("c", "r"), capacity=3, refill_per_sec=1.0)
        assert not ok
        assert wait > 0

    def test_disabled_when_capacity_zero(self) -> None:
        """capacity<=0 或 refill<=0 → 一律放行（视作未配置该桶）。"""
        limiter = TokenBucketLimiter()
        for _ in range(100):
            ok, _ = limiter.try_acquire(("c", "r"), capacity=0, refill_per_sec=1.0)
            assert ok
        for _ in range(100):
            ok, _ = limiter.try_acquire(("c", "r"), capacity=5, refill_per_sec=0.0)
            assert ok

    def test_refill_over_time(self) -> None:
        """睡 0.2 秒按 10 req/sec 应至少回到 1 个令牌。"""
        limiter = TokenBucketLimiter()
        for _ in range(1):
            assert limiter.try_acquire(("c", "r"), capacity=1, refill_per_sec=10.0)[0]
        assert not limiter.try_acquire(("c", "r"), capacity=1, refill_per_sec=10.0)[0]
        time.sleep(0.2)
        assert limiter.try_acquire(("c", "r"), capacity=1, refill_per_sec=10.0)[0]

    def test_different_keys_independent(self) -> None:
        limiter = TokenBucketLimiter()
        assert limiter.try_acquire(("a", "r"), capacity=1, refill_per_sec=1.0)[0]
        assert limiter.try_acquire(("b", "r"), capacity=1, refill_per_sec=1.0)[0]
        # 各自再来一次都被拒（桶独立耗尽）
        assert not limiter.try_acquire(("a", "r"), capacity=1, refill_per_sec=1.0)[0]
        assert not limiter.try_acquire(("b", "r"), capacity=1, refill_per_sec=1.0)[0]

    def test_purge_idle_removes_stale_buckets(self) -> None:
        limiter = TokenBucketLimiter()
        limiter.try_acquire(("c", "r"), capacity=1, refill_per_sec=1.0)
        assert limiter.snapshot()["bucket_count"] == 1
        # 立即 purge 不会清，因为 idle=0.0 之外都不算 stale
        assert limiter.purge_idle(idle_seconds=3600.0) == 0
        assert limiter.purge_idle(idle_seconds=-1.0) == 1
        assert limiter.snapshot()["bucket_count"] == 0


class TestBuildRules:
    def test_skips_invalid_entries(self) -> None:
        rules = build_rules(
            [
                {
                    "name": "ok",
                    "method": "POST",
                    "path": "/x",
                    "requests_per_minute": 60,
                    "burst": 10,
                },
                {
                    "name": "",
                    "method": "POST",
                    "path": "/x",
                    "requests_per_minute": 60,
                    "burst": 10,
                },
                {"name": "no-method", "path": "/x", "requests_per_minute": 60, "burst": 10},
                {"name": "no-rpm", "method": "POST", "path": "/x", "burst": 10},
                "not-a-dict",  # type: ignore[list-item]
                {
                    "name": "negative",
                    "method": "POST",
                    "path": "/x",
                    "requests_per_minute": -1,
                    "burst": 10,
                },
            ]
        )
        assert [r.name for r in rules] == ["ok"]

    def test_refill_per_sec_computed_from_rpm(self) -> None:
        rules = build_rules(
            [{"name": "x", "method": "POST", "path": "/x", "requests_per_minute": 60, "burst": 5}]
        )
        assert len(rules) == 1
        assert rules[0].capacity == 5
        assert rules[0].refill_per_sec == pytest.approx(1.0)


class TestRateLimitMiddleware:
    def _make_app(self, rules: list[RateLimitRule], **mw_kwargs: Any) -> FastAPI:
        app = FastAPI()
        limiter = TokenBucketLimiter()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            rules=rules,
            **mw_kwargs,
        )

        @app.post("/tasks")
        def _create() -> dict[str, str]:
            return {"ok": "1"}

        @app.post("/tasks/{task_id}/start")
        def _start(task_id: str) -> dict[str, str]:
            return {"ok": task_id}

        @app.get("/tasks")
        def _list() -> dict[str, str]:
            return {"ok": "list"}

        return app

    def test_burst_then_rate_limited(self) -> None:
        rule = RateLimitRule(
            name="create_task",
            method="POST",
            path_pattern="/tasks",
            capacity=2,
            refill_per_sec=0.001,  # 极慢 refill，确保被限
        )
        client = TestClient(self._make_app([rule]))
        assert client.post("/tasks").status_code == 200
        assert client.post("/tasks").status_code == 200
        resp = client.post("/tasks")
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in resp.headers

    def test_unmatched_paths_unaffected(self) -> None:
        rule = RateLimitRule(
            name="create_task",
            method="POST",
            path_pattern="/tasks",
            capacity=1,
            refill_per_sec=0.001,
        )
        client = TestClient(self._make_app([rule]))
        # GET /tasks 不在规则里 → 不受限
        for _ in range(10):
            assert client.get("/tasks").status_code == 200

    def test_method_specific(self) -> None:
        rule = RateLimitRule(
            name="create_task",
            method="POST",
            path_pattern="/tasks",
            capacity=1,
            refill_per_sec=0.001,
        )
        client = TestClient(self._make_app([rule]))
        assert client.post("/tasks").status_code == 200
        assert client.post("/tasks").status_code == 429
        # GET 不被限流
        assert client.get("/tasks").status_code == 200

    def test_wildcard_route_matched(self) -> None:
        rule = RateLimitRule(
            name="start_task",
            method="POST",
            path_pattern="/tasks/*/start",
            capacity=1,
            refill_per_sec=0.001,
        )
        client = TestClient(self._make_app([rule]))
        assert client.post("/tasks/abc/start").status_code == 200
        assert client.post("/tasks/abc/start").status_code == 429
        # 同样命中规则的 key=(client, rule.name)，不同 task_id 共享 → 也被拒
        assert client.post("/tasks/xyz/start").status_code == 429

    def test_trust_forwarded_uses_xff(self) -> None:
        rule = RateLimitRule(
            name="create_task",
            method="POST",
            path_pattern="/tasks",
            capacity=1,
            refill_per_sec=0.001,
        )
        client = TestClient(self._make_app([rule], trust_forwarded=True))
        # 同 XFF 的两次会被限
        assert client.post("/tasks", headers={"x-forwarded-for": "10.0.0.1"}).status_code == 200
        assert client.post("/tasks", headers={"x-forwarded-for": "10.0.0.1"}).status_code == 429
        # 不同 XFF 各自独立
        assert client.post("/tasks", headers={"x-forwarded-for": "10.0.0.2"}).status_code == 200
