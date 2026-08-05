"""阶段三：端点匹配器 — 单元测试。

覆盖：精确匹配、模板匹配、PATH_ONLY、double wildcard、
歧义候选生成、首段参数回退、重叠模板 resolution。

@note: _make_request / _make_endpoint 本地 helper 与
       tests.factories.requests.make_http_request_evidence /
       tests.factories.analysis.make_endpoint_dict 功能等价；
       此处保留本地 wrapper 是因为匹配测试对 eligibility /
       is_templated / static_prefix 有测试特定的默认值需求。
"""

from __future__ import annotations

from argus_py.correlation.enums import (
    CorrelationEligibility,
    MatchConfidence,
    MatchStrategy,
    RequestOutcome,
    RequestOwner,
    ResolutionStatus,
)
from argus_py.correlation.matcher import EndpointMatcher
from argus_py.correlation.models import HttpRequestEvidence


def _make_request(
    request_evidence_id: str = "req1",
    http_method: str = "GET",
    normalized_path: str = "/api/users",
    endpoint_match_eligibility: CorrelationEligibility = CorrelationEligibility.CONFIRMED_ELIGIBLE,
) -> HttpRequestEvidence:
    """创建最小化 HttpRequestEvidence 用于匹配测试。"""
    return HttpRequestEvidence(
        request_evidence_id=request_evidence_id,
        blackbox_run_id="bb1",
        task_id="t1",
        step_execution_id=None,
        http_method=http_method,
        normalized_path=normalized_path,
        display_path=normalized_path,
        origin="https://example.com",
        endpoint_match_eligibility=endpoint_match_eligibility,
        outcome=RequestOutcome.COMPLETED,
        request_owner=RequestOwner.FRAME,
        captured_at="2024-01-01T00:00:00",
    )


def _make_endpoint(
    endpoint_id: str,
    http_method: str,
    normalized_path_template: str,
    is_templated: bool = True,
    static_prefix: str = "",
    **overrides,
) -> dict:
    """创建最小化 endpoint dict。"""
    ep: dict = {
        "endpoint_id": endpoint_id,
        "http_method": http_method,
        "normalized_exact_path": "",
        "normalized_path_template": normalized_path_template,
        "is_templated": is_templated,
        "path_segment_count": len(normalized_path_template.strip("/").split("/")),
        "static_prefix": static_prefix,
        "controller_class": "TestController",
        "controller_method": "testMethod",
    }
    ep.update(overrides)
    return ep


class TestExactMatch:
    """精确匹配（Level 1）。"""

    def test_single_exact_match(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/users")
        result = matcher.match_batch([req], eps)
        assert len(result.evidence_list) == 1
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.EXACT
        assert ev.confidence == MatchConfidence.HIGH
        assert ev.matched_endpoint_id == "ep1"
        assert ev.candidate_count == 1
        assert len(result.candidates) == 0

    def test_multiple_exact_same_key_ambiguous(self) -> None:
        """同一个 (method, path) 有多个精确匹配 endpoint → AMBIGUOUS。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
            _make_endpoint("ep2", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/users")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.AMBIGUOUS
        assert ev.match_strategy == MatchStrategy.EXACT
        assert ev.candidate_count == 2
        assert ev.matched_endpoint_id is None

    def test_method_mismatch_exact_not_matched(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="POST", normalized_path="/api/users")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        # 精确匹配不匹配时走 PATH_ONLY
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.PATH_ONLY


class TestTemplateMatch:
    """模板匹配（Level 2）。"""

    def test_single_template_match(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep1",
                "GET",
                "/api/users/{id}",
                static_prefix="/api/users",
                path_segment_count=3,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/users/42")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.matched_endpoint_id == "ep1"
        assert ev.candidate_count == 1

    def test_overlapping_templates_unique_specificity(self) -> None:
        """P1 回归：多个模板匹配时通过 specificity 决出唯一，candidate_count=1。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_specific",
                "GET",
                "/api/v1/users/{id}",
                static_prefix="/api/v1/users",
                path_segment_count=4,
            ),
            _make_endpoint(
                "ep_generic",
                "GET",
                "/api/{version}/users/{id}",
                static_prefix="/api",
                path_segment_count=4,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/v1/users/42")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.matched_endpoint_id == "ep_specific"
        # P1 修复：重叠模板唯一匹配的 candidate_count 必须是 1
        assert ev.candidate_count == 1

    def test_first_segment_param_template(self) -> None:
        """P2 回归：首段为 {param} 的模板也能匹配。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_tenant",
                "GET",
                "/{tenant}/users",
                static_prefix="",
                path_segment_count=2,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/acme/users")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.matched_endpoint_id == "ep_tenant"

    def test_first_segment_param_path_only(self) -> None:
        """首段参数 + 方法不一致 → PATH_ONLY。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_post",
                "POST",
                "/{org}/items",
                static_prefix="",
                path_segment_count=2,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/org/items")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.PATH_ONLY

    def test_multiple_template_equal_specificity_ambiguous(self) -> None:
        """P1 回归：歧义时有多个候选，生成 EndpointEvidenceCandidate。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_a",
                "GET",
                "/api/{p1}/users/{p2}",
                static_prefix="/api",
                path_segment_count=4,
            ),
            _make_endpoint(
                "ep_b",
                "GET",
                "/api/{x1}/users/{x2}",
                static_prefix="/api",
                path_segment_count=4,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/v1/users/42")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.AMBIGUOUS
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.candidate_count == 2
        # 候选被持久化
        assert len(result.candidates) == 2
        c1, c2 = result.candidates
        assert c1.candidate_rank == 1
        assert c2.candidate_rank == 2
        assert not c1.selected
        assert not c2.selected


class TestPathOnlyMatch:
    """仅路径匹配（Level 3）。"""

    def test_single_path_only(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep_get", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="POST", normalized_path="/api/users")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.PATH_ONLY
        assert ev.confidence == MatchConfidence.LOW
        assert ev.matched_endpoint_id == "ep_get"

    def test_multiple_path_only_ambiguous(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
            _make_endpoint("ep2", "PUT", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="POST", normalized_path="/api/users")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.AMBIGUOUS
        assert ev.match_strategy == MatchStrategy.PATH_ONLY


class TestDoubleWildcard:
    """Double wildcard (**) 模板匹配。"""

    def test_double_wildcard_any_segments(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_dw",
                "GET",
                "/api/**",
                static_prefix="/api",
                path_segment_count=1,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/v1/users/42/orders")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE

    def test_double_wildcard_exact_match_preferred(self) -> None:
        """精确匹配优于 double wildcard。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep_exact", "GET", "/api/health", is_templated=False),
            _make_endpoint(
                "ep_dw",
                "GET",
                "/api/**",
                static_prefix="/api",
                path_segment_count=1,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/health")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.EXACT
        assert ev.matched_endpoint_id == "ep_exact"

    def test_double_wildcard_prefix_suffix(self) -> None:
        """前缀+**+后缀匹配模式。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_v1",
                "GET",
                "/api/v1/**/detail",
                static_prefix="/api/v1",
                path_segment_count=1,
            ),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/v1/users/42/detail")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.matched_endpoint_id == "ep_v1"


class TestUnmatched:
    """未匹配场景。"""

    def test_no_matching_endpoint(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="GET", normalized_path="/completely/different")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNMATCHED
        assert ev.match_strategy == MatchStrategy.NONE
        assert ev.confidence == MatchConfidence.UNKNOWN
        assert ev.matched_endpoint_id is None
        assert ev.candidate_count == 0

    def test_empty_endpoints_unmatched(self) -> None:
        matcher = EndpointMatcher()
        req = _make_request(http_method="GET", normalized_path="/api/users")
        result = matcher.match_batch([req], [])
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNMATCHED


class TestEligibilityFiltering:
    """请求资格过滤。"""

    def test_excluded_sw_cache_skipped(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(
            http_method="GET",
            normalized_path="/api/users",
            endpoint_match_eligibility=CorrelationEligibility.EXCLUDED_SW_CACHE,
        )
        result = matcher.match_batch([req], eps)
        assert len(result.evidence_list) == 0  # 整个跳过

    def test_attempt_only_matched_but_not_confirmed(self) -> None:
        """P2 修复：ATTEMPT_ONLY 参与匹配并产生证据，但由汇总层排除 confirmed 统计。"""
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(
            http_method="GET",
            normalized_path="/api/users",
            endpoint_match_eligibility=CorrelationEligibility.ATTEMPT_ONLY,
        )
        result = matcher.match_batch([req], eps)
        # ATTEMPT_ONLY 现在参与匹配，产生证据行
        assert len(result.evidence_list) == 1
        assert result.evidence_list[0].request_evidence_id == req.request_evidence_id
        # 请求本身的 eligibility 仍为 ATTEMPT_ONLY，
        # 汇总层通过 JOIN http_request_evidence 排除 confirmed 统计

    def test_confirmed_eligible_processed(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(
            http_method="GET",
            normalized_path="/api/users",
            endpoint_match_eligibility=CorrelationEligibility.CONFIRMED_ELIGIBLE,
        )
        result = matcher.match_batch([req], eps)
        assert len(result.evidence_list) == 1


class TestRegexParam:
    """正则参数匹配。"""

    def test_regex_param_match(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint(
                "ep_regex",
                "GET",
                "/users/{id:[0-9]+}",
                static_prefix="/users",
                path_segment_count=2,
            ),
        ]
        req_num = _make_request(http_method="GET", normalized_path="/users/12345")
        result = matcher.match_batch([req_num], eps)
        assert result.evidence_list[0].resolution_status == ResolutionStatus.UNIQUE

        req_str = _make_request(http_method="GET", normalized_path="/users/abc")
        result2 = matcher.match_batch([req_str], eps)
        assert result2.evidence_list[0].resolution_status == ResolutionStatus.UNMATCHED


class TestBatchProcessing:
    """批量匹配处理。"""

    def test_mixed_results(self) -> None:
        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
            _make_endpoint("ep2", "GET", "/api/orders/{id}", static_prefix="/api/orders"),
        ]
        reqs = [
            _make_request(
                request_evidence_id="req1", http_method="GET", normalized_path="/api/users"
            ),
            _make_request(
                request_evidence_id="req2", http_method="GET", normalized_path="/api/orders/5"
            ),
            _make_request(
                request_evidence_id="req3", http_method="GET", normalized_path="/api/nonexistent"
            ),
        ]
        result = matcher.match_batch(reqs, eps)
        assert len(result.evidence_list) == 3

        ev1 = result.evidence_list[0]
        assert ev1.request_evidence_id == "req1"
        assert ev1.resolution_status == ResolutionStatus.UNIQUE
        assert ev1.match_strategy == MatchStrategy.EXACT

        ev2 = result.evidence_list[1]
        assert ev2.request_evidence_id == "req2"
        assert ev2.resolution_status == ResolutionStatus.UNIQUE
        assert ev2.match_strategy == MatchStrategy.TEMPLATE

        ev3 = result.evidence_list[2]
        assert ev3.request_evidence_id == "req3"
        assert ev3.resolution_status == ResolutionStatus.UNMATCHED


class TestPathMapping:
    """网关前缀映射（PathMapping）在匹配前对齐浏览器侧路径与后端端点。"""

    def test_strip_prefix_matches_backend_endpoint(self) -> None:
        """浏览器侧 /api/orders/5 剥离 /api 后匹配后端 /orders/{id}。"""
        from argus_py.correlation.enums import AttemptDiagnosticCode
        from argus_py.correlation.models import PathMapping

        matcher = EndpointMatcher(
            matcher_version="v1",
            normalization_version="v1",
            path_mapping=PathMapping(strip_prefixes=["/api"]),
        )
        eps = [
            _make_endpoint("ep1", "GET", "/orders/{id}", is_templated=True),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/orders/5")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.match_strategy == MatchStrategy.TEMPLATE
        assert ev.matched_endpoint_id == "ep1"
        # 映射命中 → 诊断码
        assert AttemptDiagnosticCode.PATH_MAPPING_APPLIED in result.diagnostics

    def test_no_mapping_when_prefix_absent(self) -> None:
        """未配置前缀时请求路径原样匹配，不产生 PATH_MAPPING_APPLIED 诊断。"""
        from argus_py.correlation.enums import AttemptDiagnosticCode

        matcher = EndpointMatcher()
        eps = [
            _make_endpoint("ep1", "GET", "/orders/{id}", is_templated=True),
        ]
        req = _make_request(http_method="GET", normalized_path="/orders/5")
        result = matcher.match_batch([req], eps)
        assert result.evidence_list[0].matched_endpoint_id == "ep1"
        assert AttemptDiagnosticCode.PATH_MAPPING_APPLIED not in result.diagnostics

    def test_prepend_prefix_after_strip(self) -> None:
        """剥离 /legacy 并重挂 /api 后仍可匹配后端端点。"""
        from argus_py.correlation.models import PathMapping

        matcher = EndpointMatcher(
            matcher_version="v1",
            normalization_version="v1",
            path_mapping=PathMapping(strip_prefixes=["/legacy"], prepend_prefix="/api"),
        )
        eps = [
            _make_endpoint("ep1", "GET", "/api/users", is_templated=False),
        ]
        req = _make_request(http_method="GET", normalized_path="/legacy/users")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.matched_endpoint_id == "ep1"

    def test_strip_prefix_no_segment_boundary_no_match(self) -> None:
        """前缀按段边界匹配：/api/order 不命中 /api/orders/1 场景由索引保证。

        此处验证 strip_prefixes 不含请求前缀时原样匹配，避免误剥离。
        """
        from argus_py.correlation.models import PathMapping

        matcher = EndpointMatcher(
            matcher_version="v1",
            normalization_version="v1",
            path_mapping=PathMapping(strip_prefixes=["/admin"]),
        )
        eps = [
            _make_endpoint("ep1", "GET", "/orders/{id}", is_templated=True),
        ]
        req = _make_request(http_method="GET", normalized_path="/api/orders/5")
        result = matcher.match_batch([req], eps)
        # /admin 不命中 → 无映射，/api/orders/5 与 /orders/{id} 不匹配
        assert result.evidence_list[0].resolution_status == ResolutionStatus.UNMATCHED

    def test_prepend_root_after_strip_normalizes_trailing_slash(self) -> None:
        """剥离后为根路径再重挂前缀时，去掉尾斜杠以匹配根端点。

        回归：/legacy（根）剥离后 "/" 重挂 /api 曾产出 "/api/"，无法匹配
        规范化端点 "/api"（根路径无尾斜杠）。
        """
        from argus_py.correlation.models import PathMapping

        matcher = EndpointMatcher(
            matcher_version="v1",
            normalization_version="v1",
            path_mapping=PathMapping(strip_prefixes=["/legacy"], prepend_prefix="/api"),
        )
        eps = [
            _make_endpoint("ep1", "GET", "/api", is_templated=False),
        ]
        req = _make_request(http_method="GET", normalized_path="/legacy")
        result = matcher.match_batch([req], eps)
        ev = result.evidence_list[0]
        assert ev.resolution_status == ResolutionStatus.UNIQUE
        assert ev.matched_endpoint_id == "ep1"
