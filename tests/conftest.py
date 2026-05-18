"""pytest 根 fixture。"""

from __future__ import annotations

import pytest

from tests.helpers.factories import AppStack, make_app_stack


@pytest.fixture
def app_stack(tmp_path) -> AppStack:
    """构建完整服务栈，供需要 TaskApplicationService / TaskService / ProjectService 的测试使用。"""
    return make_app_stack(tmp_path)
