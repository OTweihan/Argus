"""验证 CLI `argus serve` 多 worker 拒启护栏与 lifespan 兜底拒启（fail-closed）。

私网部署常见误操作：K8s replicas 调大、env 设 WEB_CONCURRENCY、
直接 ``uvicorn ... --workers N``。当前 Argus 用进程内队列 / EventBus，
多副本会导致任务双发与 WS 事件丢失，必须显式拦住。

O-01/O-02 的 fail-closed 护栏：
- ``_raise_if_multi_worker``：lifespan 兜底，检测到多 worker env 直接抛
  RuntimeError 拒启（不只是告警）。
- ``_raise_if_exposed_without_auth``：非回环监听且未配置强 API Token 时拒启
  （标准 Compose 容器由回环宿主端口绑定收敛，用 ARGUS_BIND_LOOPBACK_ONLY 标记跳过）。
- ``_warn_loose_source_roots``：未配置白盒 allowed roots 时告警。
- 单实例锁：两个进程指向同一 outputs 时，第二个 lifespan 直接拒绝启动。
"""

from __future__ import annotations

import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from argus_py.api.app import _raise_if_multi_worker, _warn_loose_source_roots
from argus_py.cli.commands.serve import _detect_multi_worker_env, _raise_if_exposed_without_auth
from argus_py.config.server_settings import ServerSettings, load_server_settings

# argus_py.api.__init__.py 把 app 对象名占用了，直接 from import 会拿到 FastAPI
# 实例而非模块；用 importlib 显式解析模块拿其 logger 与单例锁。
_app_module = importlib.import_module("argus_py.api.app")


class TestDetectMultiWorkerEnv:
    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch) -> None:
        """每用例都清空相关 env，避免 host shell 污染。"""
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        monkeypatch.delenv("UVICORN_WORKERS", raising=False)

    def test_no_env_is_safe(self) -> None:
        assert _detect_multi_worker_env() is None

    def test_single_worker_env_is_safe(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        assert _detect_multi_worker_env() is None

    def test_zero_env_is_safe(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "0")
        assert _detect_multi_worker_env() is None

    def test_invalid_env_is_safe(self, monkeypatch) -> None:
        """非整数 env 不拒（让 uvicorn 自己报，避免 CLI 误判）。"""
        monkeypatch.setenv("WEB_CONCURRENCY", "abc")
        assert _detect_multi_worker_env() is None

    def test_web_concurrency_triggers(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        result = _detect_multi_worker_env()
        assert result == ("WEB_CONCURRENCY", 4)

    def test_uvicorn_workers_triggers(self, monkeypatch) -> None:
        monkeypatch.setenv("UVICORN_WORKERS", "2")
        result = _detect_multi_worker_env()
        assert result == ("UVICORN_WORKERS", 2)

    def test_web_concurrency_takes_priority(self, monkeypatch) -> None:
        """两个 env 都设时优先报 WEB_CONCURRENCY（更常见的 gunicorn/uvicorn 约定）。"""
        monkeypatch.setenv("WEB_CONCURRENCY", "3")
        monkeypatch.setenv("UVICORN_WORKERS", "5")
        result = _detect_multi_worker_env()
        assert result == ("WEB_CONCURRENCY", 3)


class TestRaiseIfMultiWorker:
    """lifespan 兜底：可识别的多 worker env 直接抛 RuntimeError 拒启。"""

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch) -> None:
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        monkeypatch.delenv("UVICORN_WORKERS", raising=False)

    def test_no_env_is_safe(self) -> None:
        _raise_if_multi_worker()

    def test_single_worker_env_is_safe(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        _raise_if_multi_worker()

    def test_invalid_env_is_safe(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "abc")
        _raise_if_multi_worker()

    def test_web_concurrency_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        with pytest.raises(RuntimeError, match="WEB_CONCURRENCY"):
            _raise_if_multi_worker()

    def test_uvicorn_workers_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("UVICORN_WORKERS", "2")
        with pytest.raises(RuntimeError, match="UVICORN_WORKERS"):
            _raise_if_multi_worker()

    def test_web_concurrency_takes_priority(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "3")
        monkeypatch.setenv("UVICORN_WORKERS", "5")
        with pytest.raises(RuntimeError, match="WEB_CONCURRENCY"):
            _raise_if_multi_worker()


def _patch_app_deps(monkeypatch: pytest.MonkeyPatch) -> ServerSettings:
    """打桩 create_app 的构建期/启动期依赖，构造可独立运行的测试应用。

    返回的 settings 与 lifespan 闭包捕获的是同一对象。
    """
    settings = replace(load_server_settings(), llm_trace_enabled=False)
    monkeypatch.setattr(_app_module, "setup_logging", Mock())
    monkeypatch.setattr(
        _app_module,
        "load_settings",
        lambda: SimpleNamespace(ensure_output_dirs=Mock()),
    )
    monkeypatch.setattr(_app_module, "load_server_settings", lambda: settings)
    monkeypatch.setattr(_app_module, "ensure_fernet_key", Mock())
    monkeypatch.setattr(_app_module, "recover_interrupted_tasks", Mock())
    monkeypatch.setattr(_app_module, "cleanup_stale_debug_bundles", Mock())
    monkeypatch.setattr(_app_module, "stop_trace_writer", Mock())
    monkeypatch.setattr(_app_module, "shutdown_container", AsyncMock())
    monkeypatch.setattr(_app_module, "reset_all_dependencies", Mock())
    monkeypatch.setattr(
        _app_module,
        "create_container",
        lambda: SimpleNamespace(
            lifecycle_service=Mock(),
            task_read_service=Mock(),
            event_bus=Mock(),
            task_worker=Mock(),
        ),
    )
    worker = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(_app_module, "get_task_worker", lambda: worker)
    return settings


def _patch_lock(monkeypatch: pytest.MonkeyPatch, acquired: bool) -> Mock:
    """把 SingleInstanceLock 替换为可控实例；返回该 mock。"""
    lock = Mock()
    lock.acquire.return_value = acquired
    monkeypatch.setattr(_app_module, "SingleInstanceLock", Mock(return_value=lock))
    return lock


class TestLifespanRejectMultiWorker:
    """运维绕过 CLI 直接 ``uvicorn --workers N`` 时，lifespan 应抛错拒启。"""

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch) -> None:
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        monkeypatch.delenv("UVICORN_WORKERS", raising=False)

    @pytest.mark.asyncio
    async def test_lifespan_raises_when_web_concurrency_gt_1(self, monkeypatch) -> None:
        _patch_app_deps(monkeypatch)
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        application = _app_module.create_app()
        with pytest.raises(RuntimeError, match="WEB_CONCURRENCY"):
            async with application.router.lifespan_context(application):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_raises_when_uvicorn_workers_gt_1(self, monkeypatch) -> None:
        _patch_app_deps(monkeypatch)
        monkeypatch.setenv("UVICORN_WORKERS", "2")
        application = _app_module.create_app()
        with pytest.raises(RuntimeError, match="UVICORN_WORKERS"):
            async with application.router.lifespan_context(application):
                pass


class TestLifespanSingletonLock:
    """lifespan 启动时获取 outputs 目录单实例锁；拿不到直接拒启。"""

    @pytest.mark.asyncio
    async def test_rejects_startup_when_lock_held(self, monkeypatch) -> None:
        _patch_app_deps(monkeypatch)
        _patch_lock(monkeypatch, acquired=False)
        application = _app_module.create_app()
        with pytest.raises(RuntimeError, match="已有 Argus 进程"):
            async with application.router.lifespan_context(application):
                pass

    @pytest.mark.asyncio
    async def test_acquires_lock_and_releases_on_shutdown(self, monkeypatch) -> None:
        _patch_app_deps(monkeypatch)
        lock = _patch_lock(monkeypatch, acquired=True)
        application = _app_module.create_app()
        async with application.router.lifespan_context(application):
            # lifespan 初始化完成后容器状态应写入 app.state，供 /ready 读取。
            assert getattr(application.state, "container", None) is not None
            assert application.state.lifespan_ready is True
        lock.release.assert_called_once()

    @pytest.mark.asyncio
    async def test_releases_lock_when_container_creation_fails(self, monkeypatch) -> None:
        _patch_app_deps(monkeypatch)
        lock = _patch_lock(monkeypatch, acquired=True)

        def _boom() -> SimpleNamespace:
            raise RuntimeError("容器初始化失败")

        monkeypatch.setattr(_app_module, "create_container", _boom)
        application = _app_module.create_app()
        with pytest.raises(RuntimeError, match="容器初始化失败"):
            async with application.router.lifespan_context(application):
                pass
        lock.release.assert_called_once()


class TestRejectExposedWithoutAuth:
    """非回环监听必须配置强 API Token（O-01 fail-closed 兜底）。"""

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch) -> None:
        monkeypatch.delenv("ARGUS_API_TOKEN", raising=False)
        monkeypatch.delenv("ARGUS_WHITEBOX_SOURCE_WORK_DIR", raising=False)
        monkeypatch.delenv("ARGUS_BIND_LOOPBACK_ONLY", raising=False)

    def test_loopback_is_allowed(self) -> None:
        _raise_if_exposed_without_auth("127.0.0.1")

    def test_localhost_is_allowed(self) -> None:
        _raise_if_exposed_without_auth("localhost")

    def test_non_loopback_without_token_is_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="ARGUS_API_TOKEN"):
            _raise_if_exposed_without_auth("0.0.0.0")

    def test_non_loopback_with_strong_token_is_allowed(self, monkeypatch) -> None:
        monkeypatch.setenv("ARGUS_API_TOKEN", "a" * 32)
        _raise_if_exposed_without_auth("0.0.0.0")

    def test_non_loopback_with_short_token_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("ARGUS_API_TOKEN", "secret")
        with pytest.raises(RuntimeError, match="至少 32 字符"):
            _raise_if_exposed_without_auth("0.0.0.0")

    def test_non_loopback_with_placeholder_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("ARGUS_API_TOKEN", "CHANGE_ME_" + "x" * 32)
        with pytest.raises(RuntimeError, match="占位值"):
            _raise_if_exposed_without_auth("0.0.0.0")

    def test_compose_container_binding_is_silent(self, monkeypatch) -> None:
        """标准 Compose 容器内 uvicorn 必须监听 0.0.0.0；宿主端口可见性由 compose
        的 127.0.0.1 绑定控制，因此带 ARGUS_BIND_LOOPBACK_ONLY 标记时允许。"""
        monkeypatch.setenv("ARGUS_BIND_LOOPBACK_ONLY", "1")
        _raise_if_exposed_without_auth("0.0.0.0")

    def test_false_loopback_marker_does_not_bypass_guard(self, monkeypatch) -> None:
        monkeypatch.setenv("ARGUS_BIND_LOOPBACK_ONLY", "false")
        with pytest.raises(RuntimeError, match="ARGUS_API_TOKEN"):
            _raise_if_exposed_without_auth("0.0.0.0")

    def test_intranet_override_without_marker_is_rejected(self) -> None:
        """内网覆盖清空回环标记后，非回环监听且无 Token 必须拒绝。"""
        with pytest.raises(RuntimeError, match="ARGUS_API_TOKEN"):
            _raise_if_exposed_without_auth("0.0.0.0")

    def test_bare_metal_source_work_dir_still_rejected(self, monkeypatch) -> None:
        """裸机即使设置 source work dir，只要没回环标记/Token 仍应拒绝。"""
        monkeypatch.setenv("ARGUS_WHITEBOX_SOURCE_WORK_DIR", "/tmp/sources")
        with pytest.raises(RuntimeError, match="ARGUS_API_TOKEN"):
            _raise_if_exposed_without_auth("0.0.0.0")


class TestWarnLooseSourceRoots:
    """未配置白盒 allowed source roots 时应告警（O-01 宽松模式过渡期）。"""

    @staticmethod
    def _capture_warnings(monkeypatch) -> list[str]:
        calls: list[str] = []

        def _record(msg: str, *args: object, **kwargs: object) -> None:
            calls.append(msg % args if args else msg)

        monkeypatch.setattr(_app_module.logger, "warning", _record)
        return calls

    def test_empty_roots_warns(self, monkeypatch) -> None:
        calls = self._capture_warnings(monkeypatch)
        _warn_loose_source_roots(ServerSettings(whitebox_allowed_source_roots=[]))
        assert any("allowed_source_roots" in c and "宽松模式" in c for c in calls)

    def test_configured_roots_is_silent(self, monkeypatch) -> None:
        calls = self._capture_warnings(monkeypatch)
        _warn_loose_source_roots(ServerSettings(whitebox_allowed_source_roots=["/tmp/sources"]))
        assert calls == []
