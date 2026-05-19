"""页面结构化快照 — 拆分子模块。"""

# Data models
# Playwright DOM capture
from argus_py.browser.snapshot.dom_eval import capture_snapshot

# HTML pipeline (internal, exported for tests)
from argus_py.browser.snapshot.html_pipeline import (
    _compress_whitespace,
    _filter_element_attributes,
    _redact_attr_value,
    _remove_block_tags,
)
from argus_py.browser.snapshot.html_pipeline import clean_html_for_prompt as _clean_html_for_prompt
from argus_py.browser.snapshot.meta import ConsoleMessage, InteractiveElement, PageSnapshot

__all__ = [
    "ConsoleMessage",
    "InteractiveElement",
    "PageSnapshot",
    "capture_snapshot",
    # Used by tests only:
    "_clean_html_for_prompt",
    "_compress_whitespace",
    "_filter_element_attributes",
    "_redact_attr_value",
    "_remove_block_tags",
]
