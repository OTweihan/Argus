"""证据采集（截图与页面快照）。"""

from __future__ import annotations

import logging

from argus_py.browser import BrowserSession, PageSnapshot
from argus_py.task.models import Task

logger = logging.getLogger(__name__)


class EvidenceCollector:
    """采集步骤截图和页面快照。"""

    async def capture_step_evidence(
        self,
        task: Task,
        session: BrowserSession,
        screenshot_path: str | None = None,
    ) -> tuple[str | None, PageSnapshot | None]:
        """为当前步骤采集截图和页面快照，失败不阻断动作结果。"""
        captured_path = screenshot_path
        if task.capture_screenshots and not captured_path:
            try:
                captured = await session.screenshot(self.screenshot_name(task), full_page=True)
                captured_path = str(captured)
            except Exception:
                logger.warning("步骤截图采集失败", exc_info=True)
                captured_path = None

        try:
            return captured_path, await session.snapshot()
        except Exception:
            logger.warning("页面快照采集失败", exc_info=True)
            return captured_path, None

    async def safe_observation(self, session: BrowserSession) -> str:
        """动作失败后尽量获取页面观察，失败时返回可读说明。"""
        try:
            snapshot = await session.snapshot()
            return snapshot.to_prompt_text()
        except Exception as exc:
            logger.debug("页面观察失败: %s", exc)
            return f"页面观察失败：{exc}"

    def screenshot_name(self, task: Task) -> str:
        """生成步骤截图文件名。"""
        return f"{task.task_id}-step-{task.current_step + 1:03d}.png"
