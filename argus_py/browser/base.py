"""浏览器会话抽象。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, Request, Response
from playwright.async_api import ConsoleMessage as PwConsoleMessage

from argus_py.browser.actions import BrowserActions
from argus_py.browser.constants import (
    DEFAULT_PAGE_READY_TIMEOUT_MS,
    DEFAULT_PAGE_SETTLE_MS,
    DEFAULT_SCREENSHOTS_DIR,
)
from argus_py.browser.errors import BrowserActionError, BrowserNotStartedError
from argus_py.browser.playwright_client import PlaywrightClient
from argus_py.browser.snapshot import ConsoleMessage, PageSnapshot, capture_snapshot
from argus_py.correlation.enums import (
    CorrelationEligibility,
    RequestOutcome,
)
from argus_py.correlation.models import _CapturedRequest
from argus_py.correlation.path_utils import (
    extract_origin,
    normalize_for_matching,
    sanitize_for_display,
)

_STOP = object()
"""Writer sentinel：通知 _request_writer 退出。"""

_ALLOWED_RESOURCE_TYPES: frozenset[str] = frozenset(
    ["document", "xhr", "fetch", "eventsource", "other"]
)
"""允许采集的资源类型；排除 image, stylesheet, font, media, script, websocket。"""

_DEFAULT_ALLOWED_METHODS: frozenset[str] = frozenset(
    ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]
)
"""默认允许的 HTTP 方法；OPTIONS 默认排除。"""


class BrowserSession:
    """封装一次测试任务内的浏览器上下文、页面、动作和观察。"""

    def __init__(
        self,
        client: PlaywrightClient | None = None,
        screenshot_dir: str | Path = DEFAULT_SCREENSHOTS_DIR,
        context_options: dict[str, Any] | None = None,
        page_ready_timeout_ms: int = DEFAULT_PAGE_READY_TIMEOUT_MS,
        page_settle_ms: int = DEFAULT_PAGE_SETTLE_MS,
        stop_browser: bool = True,
    ) -> None:
        self.client = client or PlaywrightClient()
        self.screenshot_dir = Path(screenshot_dir)
        self.context_options = context_options or {}
        self.page_ready_timeout_ms = page_ready_timeout_ms
        self.page_settle_ms = page_settle_ms
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.actions: BrowserActions | None = None
        self.console_messages: list[ConsoleMessage] = []
        self._stop_browser = stop_browser
        # 控制台消息缓冲区上限，防止长时间任务内存泄漏
        self._console_message_limit = 1000

        # ── HTTP 请求证据采集 ────────────────────────────────
        self._current_step_execution_id: str | None = None
        self._current_step_attempt: int = 0
        self._page_sequence: int = 0
        self._page_sequences: dict[int, int] = {}  # id(page) → sequence

        # 请求生命周期追踪
        self._pending_requests: dict[int, _CapturedRequest] = {}  # key = id(request)
        self._completed_requests: list[_CapturedRequest] = []

        # 单消费者持久化队列
        self._persist_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=50)
        self._writer_task: asyncio.Task[None] | None = None
        self._persist_fn: Any = None

        # 计数/过滤/上限
        self._total_observed: int = 0
        self._accepted_started: int = 0
        self._request_sequence: int = 0
        self._filtered_cross_origin: int = 0
        self._filtered_by_resource_type: int = 0
        self._filtered_by_method: int = 0
        self._filtered_websocket_count: int = 0
        self._filtered_path_too_long: int = 0
        self._dropped_pending_limit: int = 0
        self._dropped_run_limit: int = 0
        self._dropped_writer_queue_limit: int = 0
        self._writer_retry_count: int = 0
        self._writer_failed_batch_count: int = 0
        self._persistence_failed: int = 0
        self._truncated: bool = False

        # 可配置上限
        self._max_pending_requests: int = 2000
        self._max_requests_per_run: int = 100_000
        self._flush_batch_threshold: int = 200

        # 同源/方法过滤
        self._allowed_origins: list[str] = []
        self._allowed_methods: frozenset[str] = _DEFAULT_ALLOWED_METHODS
        self._allow_http_to_https_upgrade: bool = False
        self._trusted_origin_aliases: dict[str, list[str]] = {}

    async def start(self) -> "BrowserSession":
        """启动浏览器会话。"""
        await self.client.start()
        self.context = await self.client.new_context(**self.context_options)
        self.page = await self.client.new_page(self.context)
        self.page.on("console", self._on_console)

        # ── HTTP 请求证据采集（Context 级别监听）──
        self.context.on("request", self._on_request)
        self.context.on("response", self._on_response)
        self.context.on("requestfinished", self._on_request_finished)
        self.context.on("requestfailed", self._on_request_failed)
        self.context.on("page", self._on_page)

        self.actions = BrowserActions(
            self.page,
            screenshot_dir=self.screenshot_dir,
            page_ready_timeout_ms=self.page_ready_timeout_ms,
            page_settle_ms=self.page_settle_ms,
        )
        return self

    async def stop(self) -> None:
        """关闭浏览器会话。

        当 ``stop_browser=False`` 时（复用进程级单例的场景），只关闭上下文，
        不会关闭共享的浏览器进程。
        """
        errors: list[Exception] = []
        try:
            if self.context is not None:
                await self.client.close_context(self.context)
        except Exception as exc:
            errors.append(exc)
        finally:
            self.context = None
            self.page = None
            self.actions = None

        if self._stop_browser:
            try:
                await self.client.stop()
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise BrowserActionError("stop_session", "; ".join(str(item) for item in errors))

    def require_page(self) -> Page:
        """返回当前页面，未启动时抛出异常。"""
        if self.page is None:
            raise BrowserNotStartedError("BrowserSession 尚未启动。")
        return self.page

    def require_actions(self) -> BrowserActions:
        """返回动作封装，未启动时抛出异常。"""
        if self.actions is None:
            raise BrowserNotStartedError("BrowserSession 尚未启动。")
        return self.actions

    async def goto(self, url: str) -> dict[str, Any]:
        """打开页面。"""
        return await self.require_actions().navigate(url)

    async def click(self, target: str) -> dict[str, Any]:
        """点击元素。"""
        return await self.require_actions().click(target)

    async def fill(self, target: str, text: str) -> dict[str, Any]:
        """填写输入框。"""
        return await self.require_actions().fill(target, text)

    async def screenshot(self, name: str, full_page: bool = True) -> Path:
        """保存截图。"""
        return await self.require_actions().screenshot(name, full_page=full_page)

    async def snapshot(self) -> PageSnapshot:
        """获取页面快照，包含已收集的控制台消息，采集后清空消息避免跨步骤污染。"""
        await self.require_actions().wait_for_page_ready(require_load=False)
        messages = list(self.console_messages)
        self.console_messages.clear()
        return await capture_snapshot(self.require_page(), console_messages=messages)

    def _on_console(self, message: PwConsoleMessage) -> None:
        if len(self.console_messages) >= self._console_message_limit:
            return
        page_url = self.page.url if self.page else ""
        self.console_messages.append(
            ConsoleMessage(level=message.type, text=message.text, page_url=page_url)
        )

    # ── 步骤生命周期 ─────────────────────────────────────────

    def begin_step(self, step_execution_id: str, attempt: int) -> None:
        """步骤开始：设置当前活动步骤，后续请求归属到此步骤。"""
        self._current_step_execution_id = step_execution_id
        self._current_step_attempt = attempt

    def end_step(self, step_execution_id: str) -> None:
        """步骤结束：清空活动步骤，使后续请求 step_execution_id=None。"""
        if self._current_step_execution_id == step_execution_id:
            self._current_step_execution_id = None
            self._current_step_attempt = 0

    # ── 同源/方法配置 ────────────────────────────────────────

    def set_allowed_origins(
        self,
        origins: list[str],
        trusted_aliases: dict[str, list[str]] | None = None,
        allow_http_to_https_upgrade: bool = False,
    ) -> None:
        """任务启动时固定允许的 origin 列表。"""
        self._allowed_origins = [_normalize_origin(o) for o in origins]
        self._allow_http_to_https_upgrade = allow_http_to_https_upgrade
        self._trusted_origin_aliases = trusted_aliases or {}

    # ── Writer 生命周期 ──────────────────────────────────────

    def start_request_writer(self, persist_fn: Any) -> asyncio.Task[None]:
        """启动后台 writer Task。"""
        self._persist_fn = persist_fn
        self._writer_task = asyncio.create_task(self._request_writer())
        return self._writer_task

    async def finish_request_capture(self) -> None:
        """任务结束时的完整排空序列（阻塞等待全部写入完成）。

        1. 将剩余 completed 放入队列（阻塞 put，不丢数据）
        2. pending 标记为 ABANDONED 并放入队列
        3. 发送 _STOP sentinel
        4. 等待队列全部处理完成
        5. 等待 writer 退出
        """
        # 1. 剩余 completed
        if self._completed_requests:
            await self._persist_queue.put(list(self._completed_requests))
            self._completed_requests.clear()

        # 2. pending → ABANDONED（保留已有 response_status）
        abandoned: list[_CapturedRequest] = []
        for cap in self._pending_requests.values():
            cap.outcome = RequestOutcome.ABANDONED
            cap.finished_at = _utc_now_iso()
            _resolve_eligibility(cap)
            abandoned.append(cap)
        self._pending_requests.clear()
        if abandoned:
            await self._persist_queue.put(abandoned)

        # 3. 通知 writer 退出
        await self._persist_queue.put(_STOP)

        # 4. 等待队列排空
        await self._persist_queue.join()

        # 5. 等待 writer 退出
        if self._writer_task is not None and not self._writer_task.done():
            await self._writer_task

    # ── 质量快照 ─────────────────────────────────────────────

    def get_capture_quality(self) -> dict[str, Any]:
        """返回最终累计质量快照（交由调用方构建 CaptureQuality）。"""
        return {
            "total_observed": self._total_observed,
            "accepted_started": self._accepted_started,
            "persisted_count": self._accepted_started - self._persistence_failed,
            "filtered_by_resource_type": self._filtered_by_resource_type,
            "filtered_cross_origin": self._filtered_cross_origin,
            "filtered_by_method": self._filtered_by_method,
            "filtered_websocket_count": self._filtered_websocket_count,
            "filtered_path_too_long": self._filtered_path_too_long,
            "dropped_pending_limit": self._dropped_pending_limit,
            "dropped_run_limit": self._dropped_run_limit,
            "dropped_writer_queue_limit": self._dropped_writer_queue_limit,
            "writer_retry_count": self._writer_retry_count,
            "writer_failed_batch_count": self._writer_failed_batch_count,
            "persistence_failed": self._persistence_failed,
            "truncated": self._truncated,
        }

    # ── 网络事件处理 ─────────────────────────────────────────

    def _on_page(self, page: Page) -> None:
        """新页面创建时分配序号。"""
        self._page_sequence += 1
        self._page_sequences[id(page)] = self._page_sequence

    def _on_request(self, request: Request) -> None:
        """请求开始时记录归属步骤 + 过滤 + 规范化。"""
        self._total_observed += 1

        # websocket 单独统计
        if request.resource_type == "websocket":
            self._filtered_websocket_count += 1
            return

        # 跨域过滤
        if not self._is_allowed_origin(request.url):
            self._filtered_cross_origin += 1
            return

        # 资源类型过滤
        if request.resource_type not in _ALLOWED_RESOURCE_TYPES:
            self._filtered_by_resource_type += 1
            return

        # HTTP 方法过滤
        if request.method.upper() not in self._allowed_methods:
            self._filtered_by_method += 1
            return

        # 立即规范化 + 脱敏 + 丢弃 raw URL
        origin = extract_origin(request.url)
        raw_normalized = normalize_for_matching(request.url)
        # 请求路径既用于匹配也会持久化。敏感段必须在进入 _CapturedRequest
        # 前完成脱敏，避免 JWT、magic-link token、UUID 等原文落库。
        normalized = sanitize_for_display(raw_normalized)
        display = normalized
        path_too_long = len(raw_normalized) > 512
        if path_too_long:
            self._filtered_path_too_long += 1

        # 上限检查
        if self._accepted_started >= self._max_requests_per_run:
            self._dropped_run_limit += 1
            self._truncated = True
            return
        if len(self._pending_requests) >= self._max_pending_requests:
            self._dropped_pending_limit += 1
            self._truncated = True
            return

        self._accepted_started += 1
        self._request_sequence += 1

        page_seq: int = 0
        if request.frame is not None:
            page = request.frame.page
            page_seq = self._page_sequences.get(id(page), 0)

        self._pending_requests[id(request)] = _CapturedRequest(
            sequence=self._request_sequence,
            step_execution_id=self._current_step_execution_id,
            step_attempt=self._current_step_attempt,
            page_sequence=page_seq,
            method=request.method.upper(),
            origin=origin,
            normalized_path=normalized,
            display_path=display,
            resource_type=request.resource_type,
            request_owner=("SERVICE_WORKER" if request.service_worker else "FRAME"),
            path_too_long=path_too_long,
            started_at=_utc_now_iso(),
        )

    def _on_response(self, response: Response) -> None:
        """响应到达时更新状态码和 SW 标识。"""
        cap = self._pending_requests.get(id(response.request))
        if cap is None:
            return
        cap.response_status = response.status
        cap.response_from_service_worker = bool(response.from_service_worker)

    def _on_request_finished(self, request: Request) -> None:
        """请求正常完成。"""
        cap = self._pending_requests.pop(id(request), None)
        if cap is None:
            return
        cap.finished_at = _utc_now_iso()
        cap.outcome = RequestOutcome.COMPLETED
        # response_status / response_from_service_worker are already set by _on_response,
        # which fires before requestfinished in Playwright's event ordering.
        # Fallback in case _on_response was not triggered (e.g. response body not received
        # but request was still marked finished): response() is async and cannot be called
        # from a sync event handler.
        if cap.response_status is None:
            try:
                resp = request.response()
                import asyncio as _asyncio

                if _asyncio.iscoroutine(resp):
                    # Cannot await in sync callback; _on_response should have captured it.
                    pass
                elif resp is not None:
                    cap.response_status = resp.status
                    cap.response_from_service_worker = bool(resp.from_service_worker)
            except Exception:
                pass
        _resolve_eligibility(cap)
        self._completed_requests.append(cap)
        self._flush_to_queue_if_needed()

    def _on_request_failed(self, request: Request) -> None:
        """请求失败。"""
        cap = self._pending_requests.pop(id(request), None)
        if cap is None:
            return
        cap.finished_at = _utc_now_iso()
        cap.outcome = RequestOutcome.NETWORK_FAILED
        cap.failure_code = request.failure
        cap.response_status = None
        _resolve_eligibility(cap)
        self._completed_requests.append(cap)
        self._flush_to_queue_if_needed()

    # ── 内部辅助 ─────────────────────────────────────────────

    def _flush_to_queue_if_needed(self) -> None:
        """当 completed 缓冲区达到阈值时触发异步写入。"""
        if len(self._completed_requests) >= self._flush_batch_threshold:
            batch = self._completed_requests[: self._flush_batch_threshold]
            try:
                self._persist_queue.put_nowait(batch)
            except asyncio.QueueFull:
                self._dropped_writer_queue_limit += len(batch)
                self._truncated = True
                return  # 保留在 _completed_requests，下次再尝试
            del self._completed_requests[: self._flush_batch_threshold]

    async def _request_writer(self) -> None:
        """单消费者：顺序写入，失败重试（最多 3 次）。"""
        while True:
            batch = await self._persist_queue.get()
            if batch is _STOP:
                self._persist_queue.task_done()
                return
            try:
                for retry in range(3):
                    try:
                        await self._persist_fn(batch)
                        break
                    except Exception:
                        if retry == 2:
                            self._writer_failed_batch_count += 1
                            self._persistence_failed += len(batch)
                        else:
                            self._writer_retry_count += 1
            finally:
                self._persist_queue.task_done()

    def _is_allowed_origin(self, url: str) -> bool:
        """检查 URL 是否在允许的 origin 列表中。"""
        if not self._allowed_origins:
            return True  # 未配置时允许全部
        origin = _normalize_origin(url)
        if not origin:
            return False  # blob:/data:/about: 不允许
        if origin in self._allowed_origins:
            return True
        # HTTP→HTTPS 升级
        if self._allow_http_to_https_upgrade:
            alt = _try_upgrade_origin(origin)
            if alt and alt in self._allowed_origins:
                return True
        # 可信别名
        for base, aliases in self._trusted_origin_aliases.items():
            if origin == base or origin in aliases:
                if base in self._allowed_origins:
                    return True
        return False

    async def __aenter__(self) -> "BrowserSession":
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()


# ── 模块级辅助函数 ─────────────────────────────────────────


def _utc_now_iso() -> str:
    """返回 UTC ISO 8601 时间字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _normalize_origin(url: str) -> str:
    """规范化 origin：默认端口归一化、Host 小写。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in ("blob", "data", "about"):
        return ""
    host = (parsed.hostname or "").lower()
    port: int | None = getattr(parsed, "port", None)
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    if port is not None:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _try_upgrade_origin(origin: str) -> str | None:
    """尝试 HTTP→HTTPS 升级。"""
    if origin.startswith("http://"):
        return origin.replace("http://", "https://", 1)
    elif origin.startswith("https://"):
        return origin.replace("https://", "http://", 1)
    return None


def _resolve_eligibility(cap: _CapturedRequest) -> None:
    """基于最终的生命周期结果判定端点匹配资格。"""
    if cap.path_too_long:
        cap.endpoint_match_eligibility = CorrelationEligibility.ATTEMPT_ONLY
    elif cap.request_owner == "FRAME" and cap.response_from_service_worker:
        cap.endpoint_match_eligibility = CorrelationEligibility.EXCLUDED_SW_CACHE
    elif cap.outcome == RequestOutcome.NETWORK_FAILED:
        cap.endpoint_match_eligibility = CorrelationEligibility.ATTEMPT_ONLY
    elif cap.outcome == RequestOutcome.ABANDONED:
        cap.endpoint_match_eligibility = CorrelationEligibility.ATTEMPT_ONLY
    else:
        cap.endpoint_match_eligibility = CorrelationEligibility.CONFIRMED_ELIGIBLE
