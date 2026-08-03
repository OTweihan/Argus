"""阶段三：黑白盒关联 — 端点匹配器。"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from argus_py.correlation.enums import (
    AttemptDiagnosticCode,
    CorrelationEligibility,
    MatchConfidence,
    MatchStrategy,
    ResolutionStatus,
)
from argus_py.correlation.models import (
    EndpointEvidence,
    EndpointEvidenceCandidate,
    EndpointEvidenceFlow,
    HttpRequestEvidence,
    PathMapping,
)
from argus_py.correlation.path_utils import compute_path_segments
from argus_py.correlation.validator import validate_endpoint_evidence

logger = logging.getLogger(__name__)


class SegmentType(IntEnum):
    LITERAL = 1
    PARAM = 2
    REGEX_PARAM = 3
    SINGLE_WILDCARD = 4
    DOUBLE_WILDCARD = 5


@dataclass
class _SegmentMatcher:
    """预编译的路径段匹配器。"""

    seg_type: SegmentType
    literal: str = ""
    param_name: str = ""
    compiled_regex: re.Pattern | None = None

    @classmethod
    def parse(cls, segment: str) -> _SegmentMatcher:
        """解析单个路径段。"""
        if segment == "**":
            return cls(seg_type=SegmentType.DOUBLE_WILDCARD)
        if segment == "*":
            return cls(seg_type=SegmentType.SINGLE_WILDCARD)
        if segment.startswith("{") and segment.endswith("}"):
            inner = segment[1:-1]
            # 检查是否有正则约束：{name:regex}
            if ":" in inner:
                name, regex = inner.split(":", 1)
                try:
                    compiled = re.compile(f"^{regex}$")
                except re.error:
                    compiled = None
                return cls(
                    seg_type=SegmentType.REGEX_PARAM,
                    param_name=name,
                    compiled_regex=compiled,
                )
            return cls(seg_type=SegmentType.PARAM, param_name=inner)
        return cls(seg_type=SegmentType.LITERAL, literal=segment)


_SPECIFICITY_ORDER = {
    SegmentType.LITERAL: 0,
    SegmentType.REGEX_PARAM: 1,
    SegmentType.PARAM: 2,
    SegmentType.SINGLE_WILDCARD: 3,
    SegmentType.DOUBLE_WILDCARD: 4,
}


@dataclass
class _EndpointIndex:
    """端点内存索引。"""

    # (method, path) → [endpoint_dict]
    exact: dict[tuple[str, str], list[dict[str, Any]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    # (method, seg_count, first_static) → [(endpoint_dict, compiled_segments)]
    fixed_template: dict[
        tuple[str, int, str], list[tuple[dict[str, Any], list[_SegmentMatcher]]]
    ] = field(default_factory=lambda: defaultdict(list))
    # (method, min_seg_count) → [(endpoint_dict, compiled_segments)]
    double_wildcard: dict[tuple[str, int], list[tuple[dict[str, Any], list[_SegmentMatcher]]]] = (
        field(default_factory=lambda: defaultdict(list))
    )
    # path_only: dict[path] → list[endpoint_dict]
    path_only_exact: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    # (seg_count, first_static) → [(endpoint_dict, compiled_segments)]
    path_only_fixed: dict[tuple[int, str], list[tuple[dict[str, Any], list[_SegmentMatcher]]]] = (
        field(default_factory=lambda: defaultdict(list))
    )
    # min_seg_count → [(endpoint_dict, compiled_segments)]
    path_only_double_wildcard: dict[int, list[tuple[dict[str, Any], list[_SegmentMatcher]]]] = (
        field(default_factory=lambda: defaultdict(list))
    )


def _segments_match(req_segments: list[str], template_segments: list[_SegmentMatcher]) -> bool:
    """逐段比较：请求路径是否匹配预编译的模板。"""
    # double wildcard 可以匹配任意多段
    if any(s.seg_type == SegmentType.DOUBLE_WILDCARD for s in template_segments):
        return _match_with_double_wildcard(req_segments, template_segments)

    if len(req_segments) != len(template_segments):
        return False

    for req_seg, tmpl_seg in zip(req_segments, template_segments, strict=True):
        if tmpl_seg.seg_type == SegmentType.LITERAL:
            if req_seg != tmpl_seg.literal:
                return False
        elif tmpl_seg.seg_type in (SegmentType.PARAM, SegmentType.SINGLE_WILDCARD):
            if not req_seg:
                return False
        elif tmpl_seg.seg_type == SegmentType.REGEX_PARAM:
            if tmpl_seg.compiled_regex is None:
                # 不可编译的正则 → 按普通参数匹配
                if not req_seg:
                    return False
            else:
                if not tmpl_seg.compiled_regex.match(req_seg):
                    return False
    return True


def _match_with_double_wildcard(
    req_segments: list[str], template_segments: list[_SegmentMatcher]
) -> bool:
    """含 ** 的模板匹配。"""
    dw_idx = next(
        i for i, s in enumerate(template_segments) if s.seg_type == SegmentType.DOUBLE_WILDCARD
    )

    # 前后缀匹配
    prefix = template_segments[:dw_idx]
    suffix = template_segments[dw_idx + 1 :]

    # 前缀和请求开头匹配
    if len(prefix) > len(req_segments):
        return False
    if not _segments_match(req_segments[: len(prefix)], prefix):
        return False

    # 后缀和请求结尾匹配
    if len(suffix) > len(req_segments) - len(prefix):
        return False
    if not _segments_match(req_segments[len(req_segments) - len(suffix) :], suffix):
        return False

    return True


def _compute_specificity(
    endpoint: dict[str, Any], compiled: list[_SegmentMatcher]
) -> tuple[int, ...]:
    """计算模板的具体度。"""
    literal_count = sum(1 for s in compiled if s.seg_type == SegmentType.LITERAL)
    regex_param_count = sum(1 for s in compiled if s.seg_type == SegmentType.REGEX_PARAM)
    plain_param_count = sum(1 for s in compiled if s.seg_type == SegmentType.PARAM)
    single_wc_count = sum(1 for s in compiled if s.seg_type == SegmentType.SINGLE_WILDCARD)
    double_wc_count = sum(1 for s in compiled if s.seg_type == SegmentType.DOUBLE_WILDCARD)
    static_prefix_len = len(endpoint.get("static_prefix") or "")

    return (
        literal_count,
        regex_param_count,
        -plain_param_count,
        -single_wc_count,
        -double_wc_count,
        static_prefix_len,
    )


def _resolve_candidate_confidence(
    strategy: MatchStrategy,
    endpoint: dict[str, Any],
) -> MatchConfidence:
    """推导单个候选端点的置信度。

    - EXACT 歧义：候选端点本身都是精确匹配，置信度 HIGH。
    - TEMPLATE：检查模板中是否有正则约束。
    - PATH_ONLY：方法不一致，置信度 LOW。
    """
    if strategy == MatchStrategy.EXACT:
        return MatchConfidence.HIGH
    if strategy == MatchStrategy.TEMPLATE:
        has_unportable = False
        tp = endpoint.get("normalized_path_template") or ""
        for seg in tp.split("/"):
            if seg.startswith("{") and seg.endswith("}"):
                inner = seg[1:-1]
                if ":" in inner:
                    has_unportable = True
        return MatchConfidence.MEDIUM if has_unportable else MatchConfidence.HIGH
    return MatchConfidence.LOW


@dataclass
class MatchResult:
    """一次批量匹配的完整结果。"""

    evidence_list: list[EndpointEvidence] = field(default_factory=list)
    candidates: list[EndpointEvidenceCandidate] = field(default_factory=list)
    flows: list[EndpointEvidenceFlow] = field(default_factory=list)
    diagnostics: list[AttemptDiagnosticCode] = field(default_factory=list)


@dataclass
class _SingleMatchResult:
    """单次请求匹配的内部结果。"""

    evidence: EndpointEvidence
    candidate_endpoints: list[dict[str, Any]] = field(default_factory=list)


class EndpointMatcher:
    """将黑盒 HTTP 请求与白盒端点进行匹配。"""

    def __init__(
        self,
        matcher_version: str = "v1",
        normalization_version: str = "v1",
        path_mapping: PathMapping | None = None,
    ) -> None:
        self._matcher_version = matcher_version
        self._normalization_version = normalization_version
        self._path_mapping = path_mapping
        self._index: _EndpointIndex | None = None

    def build_indices(self, endpoints: list[dict[str, Any]]) -> None:
        """构造多层内存索引。"""
        idx = _EndpointIndex()

        for ep in endpoints:
            method = ep.get("http_method", "")
            path = ep.get("normalized_exact_path") or ep.get("normalized_path_template", "")
            is_templated = bool(ep.get("is_templated"))
            seg_count = int(ep.get("path_segment_count") or 0)
            first_static = (ep.get("static_prefix") or "").lstrip("/")
            template_path = ep.get("normalized_path_template", "")

            # 精确匹配索引
            if not is_templated and path:
                idx.exact[(method, path)].append(ep)

            # 模板索引
            if is_templated and template_path:
                compiled = [_SegmentMatcher.parse(s) for s in template_path.split("/") if s]
                has_dw = any(s.seg_type == SegmentType.DOUBLE_WILDCARD for s in compiled)

                if has_dw:
                    # min_seg_count = 非 ** 段的数量（** 可匹配 0..N 段）
                    min_seg = sum(1 for s in compiled if s.seg_type != SegmentType.DOUBLE_WILDCARD)
                    idx.double_wildcard[(method, min_seg)].append((ep, compiled))
                else:
                    first_static = first_static.split("/")[0] if first_static else ""
                    idx.fixed_template[(method, seg_count, first_static)].append((ep, compiled))

            # 仅路径索引（忽略 method）
            if not is_templated and path:
                idx.path_only_exact[path].append(ep)
            elif is_templated and template_path:
                compiled = [_SegmentMatcher.parse(s) for s in template_path.split("/") if s]
                has_dw = any(s.seg_type == SegmentType.DOUBLE_WILDCARD for s in compiled)
                if has_dw:
                    min_seg = sum(1 for s in compiled if s.seg_type != SegmentType.DOUBLE_WILDCARD)
                    idx.path_only_double_wildcard[min_seg].append((ep, compiled))
                else:
                    idx.path_only_fixed[(seg_count, first_static)].append((ep, compiled))

        self._index = idx

    def match_batch(
        self,
        requests: list[HttpRequestEvidence],
        endpoints: list[dict[str, Any]],
    ) -> MatchResult:
        """批量匹配请求 → 端点。"""
        if self._index is None:
            self.build_indices(endpoints)

        result = MatchResult()

        for req in requests:
            if req.endpoint_match_eligibility in (
                CorrelationEligibility.EXCLUDED_SW_CACHE,
                CorrelationEligibility.ATTEMPT_ONLY,
            ):
                continue

            single = self._match_single(req)
            validate_endpoint_evidence(single.evidence)
            result.evidence_list.append(single.evidence)

            # 歧义 → 构造 EndpointEvidenceCandidate
            if single.evidence.resolution_status == ResolutionStatus.AMBIGUOUS:
                _strategy = single.evidence.match_strategy
                for rank, ep in enumerate(single.candidate_endpoints, start=1):
                    result.candidates.append(
                        EndpointEvidenceCandidate(
                            endpoint_evidence_id=single.evidence.endpoint_evidence_id,
                            endpoint_id=ep.get("endpoint_id", ""),
                            candidate_rank=rank,
                            match_strategy=_strategy,
                            confidence=_resolve_candidate_confidence(_strategy, ep),
                            selected=False,
                        )
                    )

        return result

    def _match_single(self, req: HttpRequestEvidence) -> _SingleMatchResult:
        """单次请求三级匹配。"""
        idx = self._index
        if idx is None:
            return _SingleMatchResult(evidence=self._build_unmatched(req))

        method = req.http_method
        path = req.normalized_path
        req_segments = compute_path_segments(path)

        # ── Level 1: 精确匹配 ──
        exact = idx.exact.get((method, path), [])
        if len(exact) == 1:
            return _SingleMatchResult(
                evidence=self._build_evidence(
                    req,
                    exact[0],
                    ResolutionStatus.UNIQUE,
                    MatchStrategy.EXACT,
                    MatchConfidence.HIGH,
                    1,
                )
            )
        if len(exact) > 1:
            return _SingleMatchResult(
                evidence=self._build_evidence(
                    req,
                    exact[0],
                    ResolutionStatus.AMBIGUOUS,
                    MatchStrategy.EXACT,
                    MatchConfidence.HIGH,
                    len(exact),
                ),
                candidate_endpoints=exact,
            )

        # ── Level 2: 模板匹配 ──
        template_result = self._match_template(req, method, path, req_segments, idx)
        if template_result is not None:
            return template_result

        # ── Level 3: PATH_ONLY ──
        path_only_result = self._match_path_only(req, path, req_segments, idx)
        if path_only_result is not None:
            return path_only_result

        # ── Level 4: UNMATCHED ──
        return _SingleMatchResult(evidence=self._build_unmatched(req))

    def _match_template(
        self,
        req: HttpRequestEvidence,
        method: str,
        path: str,
        req_segments: list[str],
        idx: _EndpointIndex,
    ) -> _SingleMatchResult | None:
        """模板匹配（HTTP 方法相同）。"""
        candidates: list[tuple[dict[str, Any], list[_SegmentMatcher]]] = []

        # 固定段数模板
        fixed_key = (method, len(req_segments), req_segments[0] if req_segments else "")
        candidates.extend(idx.fixed_template.get(fixed_key, []))
        # 首段为路径参数（{param}/...）时 static_prefix 为空，需额外查空首段索引
        if req_segments:
            fallback_key = (method, len(req_segments), "")
            if fallback_key != fixed_key:
                candidates.extend(idx.fixed_template.get(fallback_key, []))

        # Double wildcard 模板（按 min_seg_count 查找）
        for (dw_method, min_seg), dw_candidates in idx.double_wildcard.items():
            if dw_method == method and len(req_segments) >= min_seg:
                candidates.extend(dw_candidates)

        # 验证段匹配
        matched: list[tuple[dict[str, Any], list[_SegmentMatcher]]] = []
        for ep, compiled in candidates:
            if _segments_match(req_segments, compiled):
                matched.append((ep, compiled))

        if not matched:
            return None

        if len(matched) == 1:
            ep, compiled = matched[0]
            confidence = self._template_confidence(compiled)
            return _SingleMatchResult(
                evidence=self._build_evidence(
                    req, ep, ResolutionStatus.UNIQUE, MatchStrategy.TEMPLATE, confidence, 1
                )
            )

        # 多个候选 → 按 specificity 排序
        matched.sort(key=lambda x: _compute_specificity(x[0], x[1]), reverse=True)
        best_spec = _compute_specificity(matched[0][0], matched[0][1])
        ties = [m for m in matched if _compute_specificity(m[0], m[1]) == best_spec]

        if len(ties) == 1:
            ep, compiled = ties[0]
            confidence = self._template_confidence(compiled)
            return _SingleMatchResult(
                evidence=self._build_evidence(
                    req, ep, ResolutionStatus.UNIQUE, MatchStrategy.TEMPLATE, confidence, 1
                )
            )

        return _SingleMatchResult(
            evidence=self._build_evidence(
                req,
                ties[0][0],
                ResolutionStatus.AMBIGUOUS,
                MatchStrategy.TEMPLATE,
                MatchConfidence.MEDIUM,
                len(matched),
            ),
            candidate_endpoints=[ep for ep, _ in matched],
        )

    def _match_path_only(
        self,
        req: HttpRequestEvidence,
        path: str,
        req_segments: list[str],
        idx: _EndpointIndex,
    ) -> _SingleMatchResult | None:
        """仅路径匹配（方法不同）。"""
        candidates: list[tuple[dict[str, Any], list[_SegmentMatcher] | None]] = []

        # 精确路径（方法不同）
        for ep in idx.path_only_exact.get(path, []):
            if ep.get("http_method") != req.http_method:
                candidates.append((ep, None))

        # 固定模板（方法不同）
        fixed_key = (len(req_segments), req_segments[0] if req_segments else "")
        for ep, compiled in idx.path_only_fixed.get(fixed_key, []):
            if ep.get("http_method") != req.http_method and _segments_match(req_segments, compiled):
                candidates.append((ep, compiled))
        # 首段为路径参数时 static_prefix 为空，需额外查空首段索引
        if req_segments:
            fallback_key = (len(req_segments), "")
            if fallback_key != fixed_key:
                for ep, compiled in idx.path_only_fixed.get(fallback_key, []):
                    if ep.get("http_method") != req.http_method and _segments_match(
                        req_segments, compiled
                    ):
                        candidates.append((ep, compiled))

        # Double wildcard（方法不同）
        for min_seg, dw_candidates in idx.path_only_double_wildcard.items():
            if len(req_segments) >= min_seg:
                for ep, compiled in dw_candidates:
                    if ep.get("http_method") != req.http_method and _segments_match(
                        req_segments, compiled
                    ):
                        candidates.append((ep, compiled))

        if not candidates:
            return None

        if len(candidates) == 1:
            ep, _ = candidates[0]
            return _SingleMatchResult(
                evidence=self._build_evidence(
                    req,
                    ep,
                    ResolutionStatus.UNIQUE,
                    MatchStrategy.PATH_ONLY,
                    MatchConfidence.LOW,
                    1,
                )
            )

        return _SingleMatchResult(
            evidence=self._build_evidence(
                req,
                candidates[0][0],
                ResolutionStatus.AMBIGUOUS,
                MatchStrategy.PATH_ONLY,
                MatchConfidence.LOW,
                len(candidates),
            ),
            candidate_endpoints=[ep for ep, _ in candidates],
        )

    def _template_confidence(self, compiled: list[_SegmentMatcher]) -> MatchConfidence:
        """检查模板是否包含不可移植的正则约束。"""
        has_unportable = any(
            s.seg_type == SegmentType.REGEX_PARAM and s.compiled_regex is None for s in compiled
        )
        return MatchConfidence.MEDIUM if has_unportable else MatchConfidence.HIGH

    def _build_evidence(
        self,
        req: HttpRequestEvidence,
        endpoint: dict[str, Any],
        resolution_status: ResolutionStatus,
        match_strategy: MatchStrategy,
        confidence: MatchConfidence,
        candidate_count: int,
    ) -> EndpointEvidence:
        """构造 EndpointEvidence 记录。"""
        matched_endpoint_id = (
            endpoint.get("endpoint_id") if resolution_status == ResolutionStatus.UNIQUE else None
        )
        import uuid

        return EndpointEvidence(
            endpoint_evidence_id=f"eev:{uuid.uuid4().hex[:12]}",
            correlation_run_id="",  # 由调用方填充
            correlation_attempt_id="",
            request_evidence_id=req.request_evidence_id,
            resolution_status=resolution_status,
            match_strategy=match_strategy,
            confidence=confidence,
            matched_endpoint_id=matched_endpoint_id,
            matcher_version=self._matcher_version,
            normalization_version=self._normalization_version,
            candidate_count=candidate_count,
        )

    def _build_unmatched(self, req: HttpRequestEvidence) -> EndpointEvidence:
        """构造未匹配的 EndpointEvidence 记录。"""
        import uuid

        return EndpointEvidence(
            endpoint_evidence_id=f"eev:{uuid.uuid4().hex[:12]}",
            correlation_run_id="",
            correlation_attempt_id="",
            request_evidence_id=req.request_evidence_id,
            resolution_status=ResolutionStatus.UNMATCHED,
            match_strategy=MatchStrategy.NONE,
            confidence=MatchConfidence.UNKNOWN,
            candidate_count=0,
            matcher_version=self._matcher_version,
            normalization_version=self._normalization_version,
        )
