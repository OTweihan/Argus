"""pytest 根 fixture。"""

from __future__ import annotations

import pytest
from argus_py.api.dependencies import reset_all_dependencies

from tests.helpers.factories import AppStack, make_app_stack


@pytest.fixture(autouse=True)
def _reset_dependencies() -> None:
    """每用例前置重置 lru_cache 单例，防止依赖注入缓存跨用例污染。"""
    reset_all_dependencies()


@pytest.fixture
def app_stack(tmp_path) -> AppStack:
    """构建完整服务栈，供需要 TaskApplicationService / TaskService / ProjectService 的测试使用。"""
    return make_app_stack(tmp_path)
