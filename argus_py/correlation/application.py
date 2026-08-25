"""关联编排服务：CorrelationRun 状态推进、自动绑定与报告重生成。

组合根（runtime.container）只负责构造本服务并注入依赖；此前散落在组合根
闭包与 TaskApplicationService 中的关联业务规则（自动绑定同项目同快照分析、
UNVERIFIED 回退、bb_done→READY/WAITING_BLACKBOX 推进）统一收敛在此，
消除多处判定漂移。
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Sequence
from typing import Any

from argus_py.core.constants import utc_now_iso
from argus_py.core.ids import generate_id
from argus_py.correlation.enums import (
    AttemptStatus,
    BlackboxRunStatus,
    CorrelationRunStatus,
    EvidenceCompleteness,
    SourceAlignmentStatus,
)
from argus_py.correlation.models import (
    BlackboxRun,
    CorrelationRun,
    HttpRequestEvidence,
)
from argus_py.correlation.path_utils import compute_config_digest
from argus_py.correlation.presenters import correlation_run_to_dict
from argus_py.observability.context import run_in_thread

logger = logging.getLogger(__name__)

# 关联完成后白盒报告重生成的串行化锁（写幂等，last-write-wins）
_report_regen_lock = threading.Lock()

# 黑盒终态集合：黑盒进入任一终态后，已绑定分析的 CorrelationRun 可推进到 READY
BLACKBOX_TERMINAL_STATUSES: frozenset[BlackboxRunStatus] = frozenset(
    {
        BlackboxRunStatus.SUCCESS,
        BlackboxRunStatus.FAILED,
        BlackboxRunStatus.CANCELLED,
        BlackboxRunStatus.TIMED_OUT,
    }
)


def is_blackbox_finished(bb_run: Any) -> bool:
    """判断 BlackboxRun 是否已进入终态。"""
    return bb_run is not None and bb_run.status in BLACKBOX_TERMINAL_STATUSES


class CorrelationService:
    """黑白盒关联的应用层编排：创建/推进 CorrelationRun、认领匹配、报告重生成。

    依赖由组合根注入；服务自身不创建任何共享存储或客户端。
    """

    def __init__(
        self,
        *,
        storage: Any,
        report_generator: Any,
        save_task: Any,
        path_mapping: Any | None = None,
        gateway_strip_prefixes: Sequence[str] = (),
        gateway_prepend_prefix: str = "",
        worker_id: str = "",
    ) -> None:
        self._storage = storage
        self._report_generator = report_generator
        self._save_task = save_task
        self._path_mapping = path_mapping
        self._strip_prefixes = list(gateway_strip_prefixes)
        self._prepend_prefix = gateway_prepend_prefix
        self._worker_id = worker_id

    # ── 黑盒侧回调（BlackboxRunner 注入）─────────────────────────────

    async def persist_request_batch(self, batch: list[dict[str, Any]]) -> None:
        """将由 BrowserSession 捕获的请求证据 dict 批量写入 DB。"""
        items: list[HttpRequestEvidence] = []
        for cap in batch:
            rid = f"hre:{uuid.uuid4().hex[:12]}"
            items.append(
                HttpRequestEvidence(
                    request_evidence_id=rid,
                    blackbox_run_id=cap.get("blackbox_run_id", ""),
                    task_id=cap.get("task_id", ""),
                    step_execution_id=cap.get("step_execution_id"),
                    step_attempt=cap.get("step_attempt", 1),
                    request_sequence=cap.get("sequence", 0),
                    http_method=cap.get("method", "GET"),
                    normalized_path=cap.get("normalized_path", ""),
                    display_path=cap.get("display_path", ""),
                    origin=cap.get("origin", ""),
                    resource_type=cap.get("resource_type", "other"),
                    endpoint_match_eligibility=self._eligibility(cap),
                    response_status=cap.get("response_status"),
                    outcome=self._outcome(cap),
                    failure_code=cap.get("failure_code"),
                    request_owner=self._owner(cap),
                    response_from_service_worker=bool(
                        cap.get("response_from_service_worker", False)
                    ),
                    page_sequence=cap.get("page_sequence", 0),
                    captured_at=cap.get("started_at", ""),
                    finished_at=cap.get("finished_at"),
                )
            )
        self._storage.insert_http_request_batch(items)

    @staticmethod
    def _eligibility(cap: dict[str, Any]) -> Any:
        from argus_py.correlation.enums import CorrelationEligibility

        return CorrelationEligibility(cap.get("endpoint_match_eligibility", "CONFIRMED_ELIGIBLE"))

    @staticmethod
    def _outcome(cap: dict[str, Any]) -> Any:
        from argus_py.correlation.enums import RequestOutcome

        return RequestOutcome(cap.get("outcome", "COMPLETED"))

    @staticmethod
    def _owner(cap: dict[str, Any]) -> Any:
        from argus_py.correlation.enums import RequestOwner

        return RequestOwner(cap.get("request_owner", "FRAME"))

    def create_blackbox_run(self, task: Any) -> str:
        """创建 BlackboxRun 实例。"""
        run = BlackboxRun(
            blackbox_run_id=f"bbr:{uuid.uuid4().hex[:12]}",
            task_id=task.task_id,
            attempt=task.execution_attempt,
            status=BlackboxRunStatus.RUNNING,
            started_at=utc_now_iso(),
        )
        self._storage.create_blackbox_run(run)
        return run.blackbox_run_id

    def open_correlation_run(
        self,
        blackbox_run_id: str,
        task: Any,
    ) -> dict[str, Any] | None:
        """创建 CorrelationRun（WAITING_ANALYSIS 或 WAITING_BLACKBOX）。

        业务规则：
        - 黑盒任务带 source_resolved_commit_sha 时，尝试绑定同项目同快照的
          已有成功分析（VERIFIED）；
        - 无快照时回退取同项目最新成功分析的快照作为期望快照并标记 UNVERIFIED，
          冻结本次关联的源码边界。
        """
        digest = compute_config_digest(
            "v1",
            "v1",
            strip_prefixes=list(self._strip_prefixes),
            context_path="",
            prepend_prefix=self._prepend_prefix,
        )
        snapshot_id = getattr(task, "source_resolved_commit_sha", None) or ""
        snapshot_was_explicit = bool(snapshot_id)
        cr = CorrelationRun(
            correlation_run_id=f"cr:{uuid.uuid4().hex[:12]}",
            project_id=task.project_id or "",
            blackbox_run_id=blackbox_run_id,
            desired_source_snapshot_id=snapshot_id,
            desired_analysis_config_digest="",
            correlation_config_digest=digest,
            matcher_version="v1",
            normalization_version="v1",
            status=CorrelationRunStatus.WAITING_ANALYSIS,
            created_at=utc_now_iso(),
        )
        project_id = task.project_id or ""
        if not snapshot_id and project_id:
            latest_analysis = self._storage.get_latest_succeeded_analysis_by_project(project_id)
            if latest_analysis is not None:
                analysis_snapshot = getattr(latest_analysis, "resolved_commit_sha", None) or ""
                if analysis_snapshot:
                    snapshot_id = analysis_snapshot
                    cr.desired_source_snapshot_id = snapshot_id

        if project_id and snapshot_id:
            latest_analysis = self._storage.get_latest_succeeded_analysis_by_project(
                project_id, source_snapshot_id=snapshot_id
            )
            if latest_analysis is not None:
                cr.analysis_id = latest_analysis.analysis_id
                cr.bound_source_snapshot_id = (
                    getattr(latest_analysis, "resolved_commit_sha", None) or ""
                )
                cr.analysis_projection_version = 1
                cr.source_alignment_status = (
                    SourceAlignmentStatus.VERIFIED
                    if snapshot_was_explicit
                    else SourceAlignmentStatus.UNVERIFIED
                )
                cr.status = CorrelationRunStatus.WAITING_BLACKBOX
        try:
            self._storage.create_correlation_run(cr)
        except Exception:
            # 唯一索引冲突 → 同一 blackbox_run_id 已有关联，幂等跳过
            existing = self._storage.get_correlation_run_by_blackbox(blackbox_run_id)
            if existing is not None:
                return {
                    "correlationRunId": existing.correlation_run_id,
                    "correlation_run_id": existing.correlation_run_id,
                }
            logger.exception("创建 CorrelationRun 失败: blackbox_run_id=%s", blackbox_run_id)
            return None
        return {
            "correlationRunId": cr.correlation_run_id,
            "correlation_run_id": cr.correlation_run_id,
        }

    def finalize_blackbox_run(
        self,
        blackbox_run_id: str,
        status: str,
        quality: Any = None,
    ) -> None:
        """更新 BlackboxRun 终态 + 持久化采集质量。"""
        self._storage.update_blackbox_run_status(
            blackbox_run_id, status, completed_at=utc_now_iso()
        )
        if quality is not None:
            self._storage.upsert_capture_quality(quality)

    # ── 匹配执行 ────────────────────────────────────────────────────

    async def claim_and_execute(self, correlation_run_id: str, worker_id: str) -> None:
        """CAS 认领 + 执行关联匹配。

        WAITING_ANALYSIS 表示分析尚未完成（等白盒回调触发），直接返回；
        WAITING_BLACKBOX 在此路径意味着黑盒刚完成，推进 READY 后认领。

        所有同步 SQLite 操作均经 ``run_in_thread`` 执行：本方法被黑盒完成
        回调直接 await，重活放在事件循环上会冻结整个服务。
        """
        cr = await run_in_thread(self._storage.get_correlation_run, correlation_run_id)
        if cr is None:
            return
        if cr.status == CorrelationRunStatus.WAITING_ANALYSIS:
            return  # 分析尚未完成，等白盒回调触发
        if cr.status == CorrelationRunStatus.WAITING_BLACKBOX:
            await run_in_thread(self._storage.set_correlation_status, correlation_run_id, "READY")

        attempt = await run_in_thread(
            self._storage.claim_and_create_attempt, correlation_run_id, worker_id
        )
        if attempt is None:
            return
        try:
            try:
                await self._execute_correlation(attempt)
            except Exception:
                logger.exception("关联匹配失败: attempt=%s", attempt.correlation_attempt_id)
                await run_in_thread(
                    self._storage.complete_and_activate_attempt,
                    attempt.correlation_attempt_id,
                    AttemptStatus.FAILED,
                    EvidenceCompleteness.PARTIAL,
                )
        finally:
            await self.regen_report_after_attempt(attempt)

    async def _execute_correlation(self, attempt: Any) -> None:
        """执行端点匹配 + 调用流关联 + Finding 证据关联。

        薄委托到 ``correlation._execution.execute_correlation``。根据采集质量
        和匹配结果决定 completeness 是 COMPLETE 还是 PARTIAL，并写入对应的
        reasons 和 diagnostics。

        ``execute_correlation`` 是纯 CPU + 同步 SQLite 的重活（全量加载投影 +
        匹配 + 批量写），必须整体放入 IO 线程执行，避免阻塞事件循环。
        """
        await run_in_thread(self._execute_correlation_sync, attempt)

    def _execute_correlation_sync(self, attempt: Any) -> None:
        """``_execute_correlation`` 的同步实现（仅限 IO 线程调用）。"""
        from argus_py.correlation._execution import execute_correlation

        cr = self._storage.get_correlation_run(attempt.correlation_run_id)
        if cr is None:
            self._storage.complete_and_activate_attempt(
                attempt.correlation_attempt_id,
                AttemptStatus.FAILED.value,
                EvidenceCompleteness.PARTIAL.value,
            )
            return

        execute_correlation(self._storage, cr, attempt, path_mapping=self._path_mapping)

    # ── 白盒唤醒回调（WhiteboxRunner 注入）───────────────────────────

    async def on_whitebox_analysis_succeeded(self, task_id: str, analysis_id: str) -> None:
        """白盒分析成功后：查找 WAITING_ANALYSIS 的 CorrelationRun 并触发关联。

        绑定后按黑盒是否已完成推进 READY/WAITING_BLACKBOX，并立即尝试认领执行。
        同步绑定/认领阶段整体在 IO 线程执行（多次 SQLite 读写）；随后逐个
        执行匹配（同样在线程）并刷新报告。多个等待运行的绑定先于其执行完成，
        各运行相互独立，最终 DB 状态与逐个「绑定→执行」一致。
        """
        claimed_list = await run_in_thread(self._bind_and_claim_waiting, task_id, analysis_id)
        for claimed in claimed_list:
            try:
                await self._execute_correlation(claimed)
            except Exception:
                # 与 claim_and_execute 相同的兜底：单次匹配失败落 FAILED 终态，
                # 不让一个运行拖住同批其余已认领的运行（它们已进入 RUNNING，
                # 不兜底会卡到租约过期才被恢复）。
                logger.exception("关联匹配失败: attempt=%s", claimed.correlation_attempt_id)
                await run_in_thread(
                    self._storage.complete_and_activate_attempt,
                    claimed.correlation_attempt_id,
                    AttemptStatus.FAILED,
                    EvidenceCompleteness.PARTIAL,
                )
            finally:
                await self.regen_report_after_attempt(claimed)

    def _bind_and_claim_waiting(self, task_id: str, analysis_id: str) -> list[Any]:
        """查找并绑定 WAITING_ANALYSIS 的关联运行，返回已认领的 attempt 列表。

        仅限 IO 线程调用：全部为同步 SQLite 操作。
        """
        analysis_run = self._storage.get_analysis_run(analysis_id)
        if analysis_run is None:
            return []
        snapshot_id = getattr(analysis_run, "resolved_commit_sha", None) or ""
        if not snapshot_id:
            return []  # 无源码快照信息，无法可靠绑定

        # 获取分析任务的项目 ID，用于匹配同项目关联运行
        analysis_project_id = ""
        task_header = self._storage.load_task_header(task_id)
        if task_header:
            analysis_project_id = task_header.get("project_id", "") or ""

        waiting = self._storage.find_waiting_correlations(
            snapshot_id, project_id=analysis_project_id or None
        )
        # 若没有精确快照匹配，回退匹配空快照的 WAITING_ANALYSIS
        # （黑盒任务先于任何分析启动时，desired_source_snapshot_id 为空）
        is_fallback = False
        if not waiting and analysis_project_id:
            waiting = self._storage.find_waiting_correlations(
                "", project_id=analysis_project_id or None
            )
            is_fallback = True
        claimed: list[Any] = []
        for cr in waiting:
            if is_fallback:
                alignment = SourceAlignmentStatus.UNVERIFIED.value
            elif snapshot_id == cr.desired_source_snapshot_id:
                alignment = SourceAlignmentStatus.VERIFIED.value
            else:
                alignment = SourceAlignmentStatus.UNVERIFIED.value
            self._storage.bind_correlation_analysis(
                cr.correlation_run_id,
                analysis_id,
                snapshot_id,
                projection_version=1,
                alignment=alignment,
            )
            self._advance_after_binding(cr)
            # 尝试立即推进和认领
            attempt = self._storage.claim_and_create_attempt(cr.correlation_run_id, self._worker_id)
            if attempt is not None:
                claimed.append(attempt)
        return claimed

    def _advance_after_binding(self, cr: Any) -> None:
        """绑定分析后按黑盒完成状态推进 CorrelationRun 状态（单一事实源）。

        黑盒已终态 → READY；否则 → WAITING_BLACKBOX。
        """
        bb_run = self._storage.get_blackbox_run(cr.blackbox_run_id)
        if is_blackbox_finished(bb_run):
            self._storage.set_correlation_status(cr.correlation_run_id, "READY")
        else:
            self._storage.set_correlation_status(cr.correlation_run_id, "WAITING_BLACKBOX")

    # ── 报告重生成 ──────────────────────────────────────────────────

    def regen_report(self, analysis_id: str) -> None:
        """同步重生成白盒任务报告（含关联数据）。由关联完成路径调用。"""
        from argus_py.correlation.report_data import build_correlation_report_data
        from argus_py.report.generator import regenerate_report_for_analysis

        try:
            with _report_regen_lock:
                regenerate_report_for_analysis(
                    self._storage,
                    build_correlation_report_data,
                    self._report_generator,
                    self._save_task,
                    analysis_id,
                )
        except Exception:
            logger.exception("关联完成后白盒报告再生成失败: analysis_id=%s", analysis_id)

    async def regen_report_after_attempt(self, attempt: Any) -> None:
        """Attempt 完成（成功/失败）后刷新该分析对应的白盒报告。"""

        def _resolve_analysis_id() -> str | None:
            cr = self._storage.get_correlation_run(attempt.correlation_run_id)
            if cr is None or not cr.analysis_id:
                return None
            return cr.analysis_id

        analysis_id = await run_in_thread(_resolve_analysis_id)
        if analysis_id is None:
            return
        try:
            await run_in_thread(self.regen_report, analysis_id)
        except Exception:
            logger.exception("关联完成后报告重生成失败: analysis_id=%s", analysis_id)

    # ── 手动操作：bind / retry / recalc ─────────────────────────────

    def bind_analysis(
        self,
        correlation_run_id: str,
        analysis_id: str,
        expected_projection_version: int | None = None,
        source_mismatch_override: bool = False,
        source_mismatch_override_reason: str | None = None,
    ) -> None:
        """手动绑定白盒分析到关联运行，完成校验后推进状态。

        校验：分析必须存在且为 SUCCEEDED；分析任务与关联运行必须属于同一项目。
        绑定后会检查黑盒是否已完成，已完成则直接进入 READY 并触发一次匹配。
        """
        from datetime import datetime, timezone

        storage = self._storage

        # 1. 校验分析存在且成功
        analysis_run = storage.get_analysis_run(analysis_id)
        if analysis_run is None:
            raise ValueError(f"分析执行不存在：{analysis_id}")
        if getattr(analysis_run, "run_status", "") != "SUCCEEDED":
            raise ValueError(
                f"只有成功的分析可以绑定，当前状态：{getattr(analysis_run, 'run_status', '')}"
            )

        # 2. 校验关联运行存在且尚未绑定分析
        cr = storage.get_correlation_run(correlation_run_id)
        if cr is None:
            raise ValueError(f"关联运行不存在：{correlation_run_id}")
        if cr.analysis_id is not None:
            raise ValueError(f"关联运行已绑定分析：{cr.analysis_id}")

        # 3. 校验项目一致
        analysis_task_header = storage.load_task_header(analysis_run.task_id)
        if analysis_task_header is None:
            raise ValueError(f"分析任务不存在：{analysis_run.task_id}")
        analysis_project = analysis_task_header.get("project_id", "")
        if analysis_project and cr.project_id and analysis_project != cr.project_id:
            raise ValueError(
                f"项目不一致：关联运行项目={cr.project_id}，分析任务项目={analysis_project}"
            )

        # 4. 确定 alignment — 优先从分析读取快照
        analysis_snapshot = getattr(analysis_run, "resolved_commit_sha", None) or ""
        cr_desired = cr.desired_source_snapshot_id or ""

        # 快照不一致时必须显式 override，不允许静默绑定
        if analysis_snapshot and cr_desired and analysis_snapshot != cr_desired:
            if not source_mismatch_override:
                raise ValueError(
                    f"分析快照 ({analysis_snapshot[:8]}) 与关联运行期望快照 "
                    f"({cr_desired[:8]}) 不一致，请确认覆盖绑定。"
                )
            alignment = "USER_DECLARED"
        elif source_mismatch_override:
            alignment = "USER_DECLARED"
        elif analysis_snapshot and cr_desired and analysis_snapshot == cr_desired:
            alignment = "VERIFIED"
        else:
            alignment = "UNVERIFIED"

        # 持久化 override 审计字段
        override_at = datetime.now(timezone.utc).isoformat() if source_mismatch_override else None

        storage.bind_correlation_analysis(
            correlation_run_id,
            analysis_id,
            snapshot_id=analysis_snapshot,
            projection_version=expected_projection_version or 1,
            alignment=alignment,
            source_mismatch_overridden=source_mismatch_override,
            source_mismatch_override_by=None,  # TODO: 从 auth 上下文注入操作者
            source_mismatch_override_at=override_at,
            source_mismatch_override_reason=source_mismatch_override_reason,
        )

        # 5. 根据黑盒完成状态推进；黑盒已完成则立即认领并执行关联匹配，
        # 避免永久停在 READY。bind 的主意图（校验 + 绑定分析）已成功，
        # 匹配失败仅降级为 PARTIAL、经 completeness 对外可见；此处吞异常，
        # 避免把「绑定成功但匹配降级」误报为绑定失败。
        bb_run = storage.get_blackbox_run(cr.blackbox_run_id)
        if is_blackbox_finished(bb_run):
            storage.set_correlation_status(correlation_run_id, "READY")
            updated_cr = storage.get_correlation_run(correlation_run_id)
            if updated_cr is not None and updated_cr.analysis_id is not None:
                worker_id = generate_id("bind")
                self._claim_and_execute_matching_sync(
                    updated_cr,
                    worker_id,
                    re_raise=False,
                )
        else:
            storage.set_correlation_status(correlation_run_id, "WAITING_BLACKBOX")

    def _claim_and_execute_matching_sync(
        self,
        cr: Any,
        worker_id: str,
        *,
        re_raise: bool,
    ) -> Any | None:
        """认领关联 attempt 并同步执行匹配；失败统一落 FAILED/PARTIAL。

        ``re_raise=True`` 时把匹配异常向上传播（retry/recalc 的主操作即匹配，
        调用方需感知失败）；``False`` 时吞掉（bind 已成功完成绑定，匹配降级
        经 PARTIAL completeness 对外可见）。返回认领到的 attempt，未认领时为 None。
        """
        attempt = self._storage.claim_and_create_attempt(cr.correlation_run_id, worker_id)
        if attempt is None:
            return None
        try:
            _execute_matching_sync(
                self._storage,
                cr,
                attempt,
                on_completed=lambda analysis_id, run_id: self.regen_report(analysis_id),
                path_mapping=self._path_mapping,
            )
        except Exception:
            self._storage.complete_and_activate_attempt(
                attempt.correlation_attempt_id,
                AttemptStatus.FAILED.value,
                EvidenceCompleteness.PARTIAL.value,
            )
            if re_raise:
                raise
        return attempt

    def retry_correlation(self, correlation_run_id: str) -> str:
        """将 FAILED/PARTIAL 的关联运行重置为 READY，创建新 attempt 并同步执行匹配。"""
        storage = self._storage
        cr = storage.get_correlation_run(correlation_run_id)
        if cr is None:
            raise ValueError(f"关联运行不存在：{correlation_run_id}")
        if cr.status not in (CorrelationRunStatus.FAILED, CorrelationRunStatus.PARTIAL):
            raise ValueError(f"只有失败或部分完成的关联可以重试，当前状态：{cr.status.value}")
        if cr.analysis_id is None:
            raise ValueError("无法重试：尚未绑定白盒分析。")

        worker_id = generate_id("retry")
        storage.set_correlation_status(correlation_run_id, "READY")
        attempt = self._claim_and_execute_matching_sync(cr, worker_id, re_raise=True)
        if attempt is None:
            raise ValueError("认领关联运行失败，可能已被其他 Worker 执行。")

        return attempt.correlation_attempt_id

    def recalculate_correlation(self, correlation_run_id: str) -> dict[str, Any] | None:
        """创建新 CorrelationRun（supersedes 指向前一个）并同步执行匹配。"""
        from datetime import datetime as dt_mod
        from datetime import timezone

        storage = self._storage
        existing = storage.get_correlation_run(correlation_run_id)
        if existing is None:
            return None
        if existing.analysis_id is None:
            raise ValueError("无法重算：尚未绑定白盒分析。")

        digest = compute_config_digest(
            existing.matcher_version,
            existing.normalization_version,
        )
        new_cr = CorrelationRun(
            correlation_run_id=f"cr:{uuid.uuid4().hex[:12]}",
            project_id=existing.project_id,
            blackbox_run_id=existing.blackbox_run_id,
            desired_source_snapshot_id=existing.desired_source_snapshot_id,
            desired_analysis_config_digest=existing.desired_analysis_config_digest,
            required_analyzer_version=existing.required_analyzer_version,
            allow_partial_analysis=existing.allow_partial_analysis,
            analysis_id=existing.analysis_id,
            bound_source_snapshot_id=existing.bound_source_snapshot_id,
            analysis_projection_version=existing.analysis_projection_version,
            correlation_config_digest=digest,
            matcher_version=existing.matcher_version,
            normalization_version=existing.normalization_version,
            supersedes_correlation_run_id=existing.correlation_run_id,
            source_alignment_status=existing.source_alignment_status,
            status=CorrelationRunStatus.READY,
            created_at=dt_mod.now(timezone.utc).isoformat(),
        )
        storage.create_correlation_run(new_cr)

        # CAS 认领 + 同步执行匹配
        worker_id = generate_id("recalc")
        attempt = self._claim_and_execute_matching_sync(new_cr, worker_id, re_raise=True)
        if attempt is None:
            raise ValueError("认领关联运行失败，可能已被其他 Worker 执行。")

        return correlation_run_to_dict(new_cr)


# ── 同步匹配执行器（run_in_thread 可调用）──────────────────────────


def _execute_matching_sync(
    storage: Any,
    cr: Any,
    attempt: Any,
    on_completed: Any | None = None,
    path_mapping: Any | None = None,
) -> None:
    """关联匹配的同步实现 — 纯 CPU + 同步 SQLite 操作。

    薄委托到 ``correlation._execution.execute_correlation``（与本模块异步路径
    共用同一编排实现）。根据采集质量和匹配结果决定 completeness
    （COMPLETE/PARTIAL），并写入对应的 reasons 和 diagnostics。
    ``on_completed(analysis_id, correlation_run_id)`` 在 Attempt 落终态后调用。
    """
    from argus_py.correlation._execution import execute_correlation

    execute_correlation(
        storage,
        cr,
        attempt,
        on_completed=on_completed,
        path_mapping=path_mapping,
    )
