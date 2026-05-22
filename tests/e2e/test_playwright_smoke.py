"""真实 Playwright 冒烟测试：使用本地 HTML fixture 验证浏览器核心能力。

覆盖 launch、screenshot、snapshot、click 交互，确保浏览器集成层不退化。

所有测试标记为 ``@pytest.mark.slow``，默认被 CI 跳过，仅在有 Playwright
浏览器缓存的 job 中运行。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from argus_py.browser.base import BrowserSession
from argus_py.browser.playwright_client import PlaywrightClient

pytestmark = pytest.mark.slow

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def browser_client(tmp_path: Path) -> PlaywrightClient:
    """无头 Chromium，截图写入临时目录。"""
    return PlaywrightClient(headless=True, browser_type="chromium")


@pytest.fixture
async def session(
    browser_client: PlaywrightClient, tmp_path: Path
) -> AsyncGenerator[BrowserSession, None]:
    """启动的 BrowserSession，测试用完后自动关闭。"""
    async with BrowserSession(
        client=browser_client,
        screenshot_dir=tmp_path / "screenshots",
    ) as session:
        yield session


# ── Basic launch + snapshot ───────────────────────────────────────────────────


class TestLaunchAndSnapshot:
    """启动浏览器 → 打开本地 HTML → 截图 + 快照结构验证。"""

    async def test_navigate_and_take_screenshot(
        self, session: BrowserSession, tmp_path: Path
    ) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        shot = await session.screenshot("smoke.png")
        assert shot.exists(), "截图文件应生成"
        assert shot.stat().st_size > 500, "截图内容不应为空"

    async def test_snapshot_contains_title_and_text(self, session: BrowserSession) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        snap = await session.snapshot()
        prompt = snap.to_prompt_text()
        assert "Hello, Argus" in prompt
        assert "item 2" in prompt

    async def test_snapshot_html_summary(self, session: BrowserSession) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        snap = await session.snapshot()
        assert snap.html_summary
        assert len(snap.html_summary) > 50

    async def test_snapshot_console_messages_on_load(self, session: BrowserSession) -> None:
        """页面加载过程无异常控制台消息（纯静态页）。"""
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        snap = await session.snapshot()
        errors = [m.text for m in snap.console_messages if m.level == "error"]
        assert not errors, f"页面加载不应有 JS 错误：{errors}"

    async def test_snapshot_interactive_elements(self, session: BrowserSession) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        snap = await session.snapshot()
        selectors = [e.selector_hint() for e in snap.interactive_elements]
        # should find the button
        assert any("Click Me" in s for s in selectors), f"未找到按钮选择器：{selectors}"


# ── Click interaction ─────────────────────────────────────────────────────────


class TestClickInteraction:
    """点击交互 — 按钮点击后页面 DOM 变化验证。"""

    async def test_click_changes_dom(self, session: BrowserSession) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        await session.click("button:has-text('Click Me')")
        snap = await session.snapshot()
        assert "clicked" in snap.to_prompt_text(), "点击后页面应展示 clicked 状态"

    async def test_click_updates_dom_then_screenshot(
        self, session: BrowserSession, tmp_path: Path
    ) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        await session.click("button:has-text('Click Me')")
        shot = await session.screenshot("after-click.png")
        assert shot.exists()
        assert shot.stat().st_size > 500


# ── Form interaction ──────────────────────────────────────────────────────────


class TestFormInteraction:
    """表单交互 — fill + click 组合操作。"""

    async def test_fill_and_submit(self, session: BrowserSession) -> None:
        await session.goto(FIXTURES_DIR.joinpath("form_page.html").as_uri())
        await session.fill("input#name-input", "Argus")
        await session.click("button#submit-btn")
        snap = await session.snapshot()
        assert "Argus" in snap.to_prompt_text(), "提交后页面应展示输入值"


# ── Multiple navigation ───────────────────────────────────────────────────────


class TestMultiPageNavigation:
    """在同一会话中导航多个页面。"""

    async def test_navigate_two_fixtures_in_one_session(self, session: BrowserSession) -> None:
        await session.goto(FIXTURES_DIR.joinpath("simple_page.html").as_uri())
        snap1 = await session.snapshot()
        prompt1 = snap1.to_prompt_text()
        assert "Hello, Argus" in prompt1

        await session.goto(FIXTURES_DIR.joinpath("form_page.html").as_uri())
        snap2 = await session.snapshot()
        prompt2 = snap2.to_prompt_text()
        assert "Form Smoke Test" in prompt2
        # 第二个页面的快照不应包含第一个页面的内容
        assert "item 1" not in prompt2
