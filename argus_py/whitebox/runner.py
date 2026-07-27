"""白盒任务执行器。

编排：配置恢复 → SourceResolver → 可见性校验 → 异步作业提交/轮询 →
结果获取 → Findings 映射。

异常通过类型化 ``WhiteboxTaskError`` 子类表达，由 ``TaskRunner``
统一映射为任务终态。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from argus_py.core.constants import utc_now
from argus_py.core.enums import FindingSeverity, FindingType, TaskStatus
from argus_py.observability.context import run_in_thread
from argus_py.task.event import TaskTimelineService
from argus_py.task.lifecycle import TaskLifecycleService
from argus_py.task.models import Finding, Task
from argus_py.task.storage import TaskSQLiteStorage
from argus_py.whitebox.client import (
    VisibilityStatus,
    WhiteboxClient,
    WhiteboxJobNotFoundError,
    WhiteboxPermanentError,
    WhiteboxResultNotReadyError,
    WhiteboxTransientError,
)
from argus_py.whitebox.config import (
    ExecutionWhiteboxConfig,
    PersistedWhiteboxConfig,
    SourceType,
    WhiteboxTaskConfig,
)
from argus_py.whitebox.exceptions import (
    WhiteboxRemoteJobFailed,
    WhiteboxSourceResolutionError,
    WhiteboxTaskCancelled,
    WhiteboxTaskError,
    WhiteboxTaskTimeout,
    WhiteboxVisibilityError,
)
from argus_py.whitebox.models import (
    AnalyzerDiagnostics,
    WhiteboxFinding,
    WhiteboxResult,
)
from argus_py.whitebox.source_resolver import (
    ResolvedSource,
    SourceResolutionError,
    SourceResolver,
)

logger = logging.getLogger(__name__)


class WhiteboxRunner:
    """白盒分析任务执行器。

    编排：SourceResolver → WhiteboxClient 异步作业 → 写 Findings/产物。
    """

    def __init__(
        self,
        *,
        client: WhiteboxClient,
        source_resolver: SourceResolver | None = None,
        timeline_service: TaskTimelineService,
        lifecycle: TaskLifecycleService,
        poll_interval: float = 5.0,
        max_poll_interval: float = 10.0,
    ) -> None:
        self._client = client
        self._source_resolver = source_resolver or SourceResolver()
        self._timeline = timeline_service
        self._lifecycle = lifecycle
        self._poll_interval = poll_interval
        self._max_poll_interval = max_poll_interval

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def run(self, task: Task) -> None:
        """执行白盒分析任务。

        不返回 Task——完成时直接修改 task 对象；终态由 TaskRunner 写入。
        异常通过 ``WhiteboxTaskError`` 子类表达。
        """
        # 0. 恢复配置
        if task.whitebox_config_json:
            persisted = PersistedWhiteboxConfig.model_validate_json(task.whitebox_config_json)
            exec_config = persisted.to_execution_config()
        else:
            config = WhiteboxTaskConfig.from_legacy_parameters(task.parameters)
            exec_config = config.to_persisted().to_execution_config()

        source_repo_url = (
            persisted.source_repo_url
            if task.whitebox_config_json
            else config.to_persisted().source_repo_url
        )

        # 1. 统一 deadline
        deadline = time.monotonic() + task.timeout_seconds
        resolved: ResolvedSource | None = None
        remote_may_be_running = False

        try:
            # 2. 源码解析 + 立即持久化快照
            resolved = await self._resolve_source(exec_config, task.task_id, deadline)
            self._write_snapshot(task, resolved, source_repo_url)
            await run_in_thread(self._lifecycle.save_task, task)
            await self._safe_emit(
                "whitebox_source_resolved",
                task.task_id,
                data={
                    "source_type": resolved.source_type,
                    "commit_sha": resolved.resolved_commit_sha,
                    "content_sha256": resolved.content_sha256,
                    "ref_type": resolved.ref_type,
                    "dirty": resolved.is_dirty,
                },
            )

            # 3. 可见性校验
            await self._check_visibility(
                resolved.resolved_path,
                task.task_id,
                deadline,
            )

            # 4. 提交 + 持久化 job_id
            # 从发起 POST 开始就必须假定远端可能已接收；
            # 即使本地超时没拿到 job_id，也不能立即删除快照。
            remote_may_be_running = True
            job_id = await self._submit_job(task, resolved, exec_config)
            await self._safe_emit(
                "whitebox_submitted",
                task.task_id,
                data={"jobId": job_id},
            )

            # 5. 轮询
            await self._poll(task, job_id, deadline)
            remote_may_be_running = False

            # 6. 获取结果（含 409 重试）
            result = await self._get_result_with_retry(job_id, deadline)
            task.findings = _map_findings(
                result.findings,
                source_root=resolved.resolved_path,
            )
            diag_summary = _build_diag_summary(result.diagnostics)
            endpoint_count = len(result.endpoints)
            finding_count = len(result.findings)
            task.result_summary = (
                f"白盒分析完成。发现 {endpoint_count} 个端点、"
                f"{finding_count} 个代码缺陷/坏味道。"
                f"{diag_summary}"
            )
            task.result_json = json.dumps(
                _serialize_whitebox_result(
                    result,
                    endpoint_count,
                    finding_count,
                    exec_config.scope,
                ),
                ensure_ascii=False,
            )
            task.result_schema_version = 1
            task.result_size_bytes = len(task.result_json)

            await self._safe_emit_terminal(
                "whitebox_succeeded",
                task.task_id,
                summary=(
                    f"分析完成: {endpoint_count} 端点, "
                    f"{finding_count} 问题, "
                    f"{len(result.call_graph.nodes)} 调用图节点"
                ),
            )

            logger.info(
                "白盒分析完成: endpoints=%d callgraph_nodes=%d findings=%d flows=%d clusters=%d",
                endpoint_count,
                len(result.call_graph.nodes),
                finding_count,
                len(result.execution_flows),
                len(result.clusters),
            )

        except WhiteboxTaskCancelled as exc:
            await self._safe_emit_terminal(
                "whitebox_cancelled",
                task.task_id,
                summary=str(exc),
                data={
                    "jobId": exc.job_id,
                    "origin": exc.origin,
                    "errorCode": exc.error_code,
                },
            )
            raise
        except WhiteboxTaskTimeout as exc:
            await self._safe_emit_terminal(
                "whitebox_timed_out",
                task.task_id,
                summary=str(exc),
                data={
                    "jobId": exc.job_id,
                    "errorCode": exc.error_code,
                },
            )
            raise
        except Exception as exc:
            error_data: dict[str, object] = {}
            if hasattr(exc, "error_code") and exc.error_code:
                error_data["errorCode"] = exc.error_code
            await self._safe_emit_terminal(
                "whitebox_failed",
                task.task_id,
                summary=str(exc),
                data=error_data,
            )
            raise
        finally:
            await self._safe_flush()
            if resolved is not None and (
                not remote_may_be_running
                or task.external_job_status
                in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "EXPIRED"}
            ):
                try:
                    await run_in_thread(self._source_resolver.release, resolved)
                except Exception:
                    logger.exception("清理白盒源码快照失败: %s", resolved.resolved_path)
            elif resolved is not None and remote_may_be_running:
                logger.info(
                    "保留白盒源码快照（远端状态不确定，由 24h TTL 回收）: %s remote_status=%s",
                    resolved.resolved_path,
                    task.external_job_status,
                )

    # ── 源码解析 ──────────────────────────────────────────────────────────────

    async def _resolve_source(
        self,
        config: ExecutionWhiteboxConfig,
        task_id: str,
        deadline: float,
    ) -> ResolvedSource:
        """解析源码，剩余时间超过 10s 才开始克隆。"""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WhiteboxTaskTimeout(
                job_id="",
                deadline=0,
            )
        try:
            if config.source_type == SourceType.GIT:
                return await run_in_thread(
                    self._source_resolver.resolve,
                    config.repo_url,
                    config.ref,
                    clone_id=task_id,
                )
            return await run_in_thread(
                self._source_resolver.resolve_path,
                config.source_path,
                snapshot_id=task_id,
            )
        except SourceResolutionError as exc:
            raise WhiteboxSourceResolutionError(str(exc)) from exc

    def _write_snapshot(
        self,
        task: Task,
        resolved: ResolvedSource,
        source_repo_url: str | None,
    ) -> None:
        """将源码快照写入 task（不持久化——调用方负责 save）。"""
        task.source_type = resolved.source_type
        task.source_repo_url = source_repo_url
        task.source_requested_ref = resolved.requested_ref
        task.source_resolved_commit_sha = resolved.resolved_commit_sha
        task.source_ref_type = resolved.ref_type
        task.source_dirty = resolved.is_dirty

    # ── 可见性校验 ────────────────────────────────────────────────────────────

    async def _check_visibility(
        self,
        resolved_path: str,
        task_id: str,
        deadline: float,
    ) -> None:
        """验证 Python 和 Java 均能访问源码路径。"""
        local_path = Path(resolved_path)
        if not local_path.is_dir():
            raise WhiteboxVisibilityError(f"源码路径不存在: {resolved_path}")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WhiteboxTaskTimeout(job_id="", deadline=0)

        visibility = await self._client.validate_source(resolved_path)

        if visibility.status is VisibilityStatus.ENDPOINT_UNSUPPORTED:
            raise WhiteboxVisibilityError(
                f"Java 不支持 validate-source 端点，"
                f"请升级 Java 分析器或确认版本兼容。"
                f"（原因: {visibility.reason}）"
            )
        if visibility.status is VisibilityStatus.ANALYZER_UNAVAILABLE:
            raise WhiteboxVisibilityError(
                f"Java 分析器不可达，无法完成跨进程可见性校验。（原因: {visibility.reason}）"
            )
        if visibility.status is not VisibilityStatus.VALIDATED:
            raise WhiteboxVisibilityError(visibility.reason or "可见性校验失败")
        if not visibility.readable:
            raise WhiteboxVisibilityError(
                f"Java 无法读取源码路径: {resolved_path}。"
                f"容器部署请确保 Python 与 Java 使用共享卷挂载同一路径。"
            )
        # 校验成功
        await self._safe_emit(
            "whitebox_source_validated",
            task_id,
            data={"validated": True},
        )

    # ── 提交作业 ──────────────────────────────────────────────────────────────

    async def _submit_job(
        self,
        task: Task,
        resolved: ResolvedSource,
        config: ExecutionWhiteboxConfig,
    ) -> str:
        """提交异步分析作业并立即持久化 job_id。"""
        job_status = await self._client.submit_analyze_job(
            source_path=resolved.resolved_path,
            scope=config.scope,
            maven=config.maven.model_dump(exclude_none=True, by_alias=True)
            if config.maven
            else None,
            target_modules=config.target_modules or None,
            client_request_id=f"{task.task_id}:{task.execution_attempt}",
        )
        job_id = job_status.job_id
        task.external_job_id = job_id
        task.external_job_status = job_status.status
        task.external_job_submitted_at = utc_now().isoformat()
        await run_in_thread(self._lifecycle.save_task, task)
        logger.info("白盒分析作业已提交: job_id=%s task=%s", job_id, task.task_id)
        return job_id

    # ── 轮询 ──────────────────────────────────────────────────────────────────

    async def _poll(
        self,
        task: Task,
        job_id: str,
        baseline_deadline: float,
    ) -> None:
        """轮询 Java 作业状态直到终态。"""
        last_sequence = -1
        seen_event_ids: set[str] = set()
        consecutive_errors = 0

        while True:
            # 取消检查
            token = self._lifecycle.get_cancellation_token(task.task_id)
            if token.is_cancelled:
                # 阶段一：只停止轮询，不尝试取消远端作业
                # Java 没有可协作取消机制，调用 DELETE 只会设置状态而不会中断分析线程
                logger.warning(
                    "任务 %s 已取消，停止轮询远端作业 %s（远端作业可能仍在运行）",
                    task.task_id,
                    job_id,
                )
                raise WhiteboxTaskCancelled(
                    job_id=job_id,
                    origin="local",
                )

            remaining = baseline_deadline - time.monotonic()
            if remaining <= 0:
                raise WhiteboxTaskTimeout(
                    job_id=job_id,
                    deadline=task.timeout_seconds,
                )

            # 动态 request timeout（不超过剩余时间）
            request_timeout = min(
                self._client.request_timeout,
                max(remaining, 0.5),
            )

            try:
                job_status = await self._client.get_analyze_job(
                    job_id,
                    timeout=request_timeout,
                )
                consecutive_errors = 0
            except WhiteboxTransientError as exc:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise WhiteboxTaskError(f"连续 {consecutive_errors} 次轮询瞬时失败") from exc
                delay = min(2**consecutive_errors, self._max_poll_interval)
                # sleep 不超过剩余时间
                await asyncio.sleep(min(delay, max(remaining, 0)))
                continue
            except WhiteboxJobNotFoundError as exc:
                raise WhiteboxTaskError(f"远端作业 {job_id} 不存在，可能已过期") from exc
            except WhiteboxPermanentError:
                raise

            # 窄字段更新（不覆盖并发终态）
            task.external_job_status = job_status.status
            task.external_job_last_polled_at = utc_now().isoformat()
            if isinstance(self._lifecycle.storage, TaskSQLiteStorage):
                await run_in_thread(
                    self._lifecycle.storage.update_external_job_checkpoint,
                    task.task_id,
                    external_job_status=job_status.status,
                    external_job_last_polled_at=task.external_job_last_polled_at,
                    expected_status=TaskStatus.RUNNING.value,
                )

            # 事件去重（按 sequence + eventId；兼容旧版无此字段的 Java）
            for evt in sorted(job_status.events, key=lambda e: e.sequence):
                if evt.event_id and evt.event_id in seen_event_ids:
                    continue
                # 仅当 sequence >= 0 且未超过去重窗口时才跳过
                if evt.sequence >= 0 and evt.sequence <= last_sequence:
                    continue
                if evt.sequence >= 0 and evt.sequence > last_sequence + 1:
                    logger.debug(
                        "事件 sequence 缺口: %d→%d",
                        last_sequence,
                        evt.sequence,
                    )
                if evt.event_id:
                    seen_event_ids.add(evt.event_id)
                if evt.sequence >= 0:
                    last_sequence = evt.sequence
                await self._safe_emit(
                    "whitebox_progress",
                    task.task_id,
                    summary=evt.message,
                    data={
                        "stage": evt.stage,
                        "sequence": evt.sequence,
                        "eventId": evt.event_id,
                    },
                )

            # 终态判断（映射表）
            status = job_status.status
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                raise WhiteboxRemoteJobFailed(
                    job_id=job_id,
                    error=job_status.error,
                )
            if status == "CANCELLED":
                raise WhiteboxTaskCancelled(
                    job_id=job_id,
                    origin="remote",
                )
            if status == "TIMED_OUT":
                raise WhiteboxTaskTimeout(
                    job_id=job_id,
                    deadline=task.timeout_seconds,
                )
            if status == "EXPIRED":
                raise WhiteboxRemoteJobFailed(
                    job_id=job_id,
                    error="远端作业已过期",
                )
            if status in ("PENDING", "RUNNING"):
                await asyncio.sleep(min(self._poll_interval, max(remaining, 0)))
                continue
            # 未知状态 → 协议失败
            raise WhiteboxTaskError(f"未知作业状态: {status}")

    # ── 获取结果 ──────────────────────────────────────────────────────────────

    async def _get_result_with_retry(
        self,
        job_id: str,
        deadline: float,
    ) -> WhiteboxResult:
        """获取结果，409 在 deadline 内重试。"""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WhiteboxTaskTimeout(
                    job_id=job_id,
                    deadline=0,
                )

            request_timeout = min(
                self._client.request_timeout,
                max(remaining, 0.5),
            )

            try:
                return await self._client.get_analyze_job_result(
                    job_id,
                    timeout=request_timeout,
                )
            except WhiteboxResultNotReadyError:
                await asyncio.sleep(min(1.0, remaining))

    # ── 取消远端作业 ──────────────────────────────────────────────────────────

    async def _cancel_remote_job(self, job_id: str) -> bool:
        """阶段一：不实现远端取消。

        Java 没有可协作取消机制。设置 CANCELLED 状态不会中断分析线程，
        PENDING 作业的 markRunning() 也会覆盖 CANCELLED。
        首版只停止 Python 侧轮询，明确标注"远端作业可能仍在运行"。
        """
        logger.info(
            "远端作业 %s 取消失败（阶段一未实现远端取消），只停止本地轮询",
            job_id,
        )
        return False

    # ── 时间线安全封装 ────────────────────────────────────────────────────────

    async def _safe_emit(self, event_type: str, task_id: str, **kwargs: Any) -> None:
        """发送时间线事件（best-effort，失败不覆盖业务异常）。"""
        try:
            await self._timeline.emit(task_id, event_type, phase="whitebox", **kwargs)
        except Exception:
            logger.exception("时间线事件写入失败: %s", event_type)

    async def _safe_emit_terminal(self, event_type: str, task_id: str, **kwargs: Any) -> None:
        """发送终态事件并立即 flush（best-effort）。"""
        try:
            await self._timeline.emit(task_id, event_type, phase="whitebox", **kwargs)
            await self._timeline.flush_events()
        except Exception:
            logger.exception("时间线终态事件写入失败: %s", event_type)

    async def _safe_flush(self) -> None:
        """flush 时间线缓冲区（best-effort）。"""
        try:
            await self._timeline.flush_events()
        except Exception:
            logger.exception("时间线 flush 失败")


# ── Finding 映射 ──────────────────────────────────────────────────────────────


def _map_severity(severity: str) -> FindingSeverity:
    """将 Java 端的严重级别映射到 FindingSeverity。"""
    mapping = {
        "CRITICAL": FindingSeverity.CRITICAL,
        "HIGH": FindingSeverity.HIGH,
        "MEDIUM": FindingSeverity.MEDIUM,
        "LOW": FindingSeverity.LOW,
        "INFO": FindingSeverity.INFO,
    }
    return mapping.get(severity.upper(), FindingSeverity.INFO)


def _compute_fingerprint(
    rule_id: str | None,
    file_path: str,
    line_number: int,
    title: str,
    source_root: str | None = None,
) -> str:
    """生成 Finding 的稳定指纹。

    尝试将 file_path 转换为源码根目录相对路径以实现跨执行一致性。
    """
    normalized_path: str
    if source_root:
        try:
            relative = Path(file_path).resolve().relative_to(Path(source_root).resolve())
            normalized_path = PurePosixPath(relative).as_posix()
        except (ValueError, OSError):
            normalized_path = file_path.replace("\\", "/").strip()
    else:
        normalized_path = file_path.replace("\\", "/").strip()

    return sha256(
        "\0".join(
            [
                rule_id or "",
                normalized_path,
                str(line_number),
                title.strip(),
            ]
        ).encode()
    ).hexdigest()


def _map_findings(
    whitebox_findings: list[WhiteboxFinding],
    source_root: str | None = None,
) -> list[Finding]:
    """将 WhiteboxFinding 列表映射到业务层 Finding 列表。

    语义字段 (rule_category, confidence) 保持 None——只在 Java 明确返回时才有值。
    相同 fingerprint 的去重。
    """
    findings: list[Finding] = []
    seen: set[str] = set()
    for wf in whitebox_findings:
        fp = _compute_fingerprint(
            wf.rule_id,
            wf.file_path,
            wf.line_number,
            wf.title,
            source_root=source_root,
        )
        if fp in seen:
            continue
        seen.add(fp)

        finding = Finding(
            title=wf.title,
            description=wf.description,
            severity=_map_severity(wf.severity),
            finding_type=FindingType.FUNCTIONAL,
            location=f"{wf.file_path}:{wf.line_number}",
            rule_id=wf.rule_id,
            rule_category=None,  # Java 暂不返回
            confidence=None,  # Java 暂不返回
            fingerprint=fp,
        )
        findings.append(finding)
    return findings


# ── 诊断摘要 ─────────────────────────────────────────────────────────────────


def _build_diag_summary(diagnostics: AnalyzerDiagnostics | None) -> str:
    """从诊断信息构建可读的摘要字符串。"""
    if not diagnostics:
        return ""
    cp_info = ""
    if diagnostics.classpath_available:
        cp_info = f"，classpath {diagnostics.jar_count} 个 JAR"
    elif diagnostics.classpath_source:
        cp_info = "，无 classpath（降级为源码分析）"
    return (
        f"解析文件 {diagnostics.parsed_file_count}/"
        f"{diagnostics.total_source_files}，"
        f"调用 {diagnostics.total_calls} 个"
        f"（高置信度 {diagnostics.resolved_high}，"
        f"中置信度 {diagnostics.resolved_medium}，"
        f"未解析 {diagnostics.unresolved}）{cp_info}。"
    )


# ── WhiteboxResult 序列化 ────────────────────────────────────────────────────


def _serialize_whitebox_result(
    result: WhiteboxResult,
    endpoint_count: int,
    finding_count: int,
    scope: str,
) -> dict:
    """将 WhiteboxResult 序列化为可 JSON 序列化的字典（供报告模板使用）。"""
    return {
        "endpoints": [
            {
                "path": e.path,
                "httpMethod": e.http_method,
                "controllerClass": e.controller_class,
                "controllerMethod": e.controller_method,
                "parameters": e.parameters,
                "returnType": e.return_type,
            }
            for e in result.endpoints
        ],
        "callGraph": {
            key: {
                "className": node.class_name,
                "methodName": node.method_name,
                "methodSignature": node.method_signature,
                "calleeDetails": [
                    {
                        "to": ce.to,
                        "methodName": ce.method_name,
                        "typeName": ce.type_name,
                        "resolutionType": ce.resolution_type,
                        "confidence": ce.confidence,
                        "candidates": ce.candidates,
                        "sourceFile": ce.source_file,
                        "line": ce.line,
                    }
                    for ce in node.callee_details
                ],
            }
            for key, node in result.call_graph.nodes.items()
        },
        "executionFlows": [
            {
                "entryPoint": ef.entry_point,
                "callDepth": ef.call_depth,
                "steps": [
                    {
                        "depth": s.depth,
                        "methodKey": s.method_key,
                        "className": s.class_name,
                        "methodName": s.method_name,
                    }
                    for s in ef.steps
                ],
            }
            for ef in result.execution_flows
        ],
        "clusters": [
            {
                "clusterId": c.cluster_id,
                "suggestedLabel": c.suggested_label,
                "memberKeys": c.member_keys,
                "memberCount": c.member_count,
            }
            for c in result.clusters
        ],
        "diagnostics": (
            {
                "totalSourceFiles": result.diagnostics.total_source_files,
                "parsedFileCount": result.diagnostics.parsed_file_count,
                "failedFileCount": result.diagnostics.failed_file_count,
                "failedFiles": [
                    {"file": ff.file, "problems": ff.problems}
                    for ff in result.diagnostics.failed_files
                ],
                "totalCalls": result.diagnostics.total_calls,
                "resolvedHigh": result.diagnostics.resolved_high,
                "resolvedMedium": result.diagnostics.resolved_medium,
                "resolvedLow": result.diagnostics.resolved_low,
                "unresolved": result.diagnostics.unresolved,
                "classpathAvailable": result.diagnostics.classpath_available,
                "jarCount": result.diagnostics.jar_count,
                "classpathSource": result.diagnostics.classpath_source,
                "classpathWarnings": result.diagnostics.classpath_warnings,
                "classpathErrors": result.diagnostics.classpath_errors,
                "applicationModuleCount": result.diagnostics.application_module_count,
                "businessModuleCount": result.diagnostics.business_module_count,
                "libraryModuleCount": result.diagnostics.library_module_count,
                "bomModuleCount": result.diagnostics.bom_module_count,
                "moduleTypes": result.diagnostics.module_types,
            }
            if result.diagnostics
            else None
        ),
        "summary": {
            "endpoint_count": endpoint_count,
            "call_graph_node_count": len(result.call_graph.nodes),
            "finding_count": finding_count,
            "execution_flow_count": len(result.execution_flows),
            "cluster_count": len(result.clusters),
            "scope": scope,
        },
    }
