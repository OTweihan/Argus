"""验证 CLI `argus serve` 多 worker 拒启护栏与 lifespan 兜底告警。

私网部署常见误操作：K8s replicas 调大、env 设 WEB_CONCURRENCY、
直接 ``uvicorn ... --workers N``。当前 Argus 用进程内队列 / EventBus，
多副本会导致任务双发与 WS 事件丢失，必须显式拦住。

同时覆盖 O-01 的 fail-closed 告警：
- ``_warn_exposed_without_auth``：非回环监听且未配置 API Token 时告警
  （标准 Compose 容器由回环宿主端口绑定收敛，用 ARGUS_BIND_LOOPBACK_ONLY 标记跳过）。
- ``_warn_loose_source_roots``：未配置白盒 allowed roots 时告警。
"""

from __future__ import annotations

import importlib

import pytest
from argus_py.api.app import _warn_if_multi_worker, _warn_loose_source_roots
from argus_py.cli.commands.serve import _detect_multi_worker_env, _warn_exposed_without_auth
from argus_py.config.server_settings import ServerSettings

# argus_py.api.__init__.py 把 app 对象名占用了，直接 from import 会拿到 FastAPI
# 实例而非模块；用 importlib 显式解析模块拿其 logger。
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


class TestLifespanFallback:
    """运维绕过 CLI 直接 ``uvicorn --workers N`` 时，lifespan 应打 ERROR。

    Argus 自定义日志配置可能改了 propagate，导致 pytest caplog 无法可靠
    捕获。这里直接 patch ``logger.error`` 收集调用参数，最稳。
    """

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch) -> None:
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        monkeypatch.delenv("UVICORN_WORKERS", raising=False)

    @staticmethod
    def _capture_errors(monkeypatch) -> list[str]:
        calls: list[str] = []

        def _record(msg: str, *args: object, **kwargs: object) -> None:
            calls.append(msg % args if args else msg)

        monkeypatch.setattr(_app_module.logger, "error", _record)
        return calls

    def test_no_log_when_single_worker(self, monkeypatch) -> None:
        calls = self._capture_errors(monkeypatch)
        _warn_if_multi_worker()
        assert calls == []

    def test_logs_error_when_multi_worker(self, monkeypatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        calls = self._capture_errors(monkeypatch)
        _warn_if_multi_worker()
        assert any("不支持多 worker" in c and "WEB_CONCURRENCY" in c for c in calls)

    def test_uvicorn_workers_env_also_logged(self, monkeypatch) -> None:
        monkeypatch.setenv("UVICORN_WORKERS", "3")
        calls = self._capture_errors(monkeypatch)
        _warn_if_multi_worker()
        assert any("UVICORN_WORKERS" in c for c in calls)


class TestWarnExposedWithoutAuth:
    """非回环监听且未配置 API Token 时应显式告警（O-01 fail-closed 兜底）。"""

    @pytest.fixture(autouse=True)
    def _clear(self, monkeypatch) -> None:
        monkeypatch.delenv("ARGUS_API_TOKEN", raising=False)
        monkeypatch.delenv("ARGUS_WHITEBOX_SOURCE_WORK_DIR", raising=False)
        monkeypatch.delenv("ARGUS_BIND_LOOPBACK_ONLY", raising=False)

    @staticmethod
    def _capture_warns(monkeypatch) -> list[str]:
        calls: list[str] = []
        serve_module = importlib.import_module("argus_py.cli.commands.serve")

        def _record(message: str, **kwargs: object) -> None:
            calls.append(message)

        monkeypatch.setattr(serve_module, "cli_warn", _record)
        return calls

    def test_loopback_is_silent(self, monkeypatch) -> None:
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("127.0.0.1")
        assert calls == []

    def test_localhost_is_silent(self, monkeypatch) -> None:
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("localhost")
        assert calls == []

    def test_non_loopback_without_token_warns(self, monkeypatch) -> None:
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("0.0.0.0")
        assert any("非回环" in c and "ARGUS_API_TOKEN" in c for c in calls)

    def test_non_loopback_with_token_is_silent(self, monkeypatch) -> None:
        monkeypatch.setenv("ARGUS_API_TOKEN", "secret")
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("0.0.0.0")
        assert calls == []

    def test_compose_container_binding_is_silent(self, monkeypatch) -> None:
        """标准 Compose 容器内 uvicorn 必须监听 0.0.0.0；宿主端口可见性由 compose
        的 127.0.0.1 绑定控制，因此带 ARGUS_BIND_LOOPBACK_ONLY 标记时不告警。"""
        monkeypatch.setenv("ARGUS_BIND_LOOPBACK_ONLY", "1")
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("0.0.0.0")
        assert calls == []

    def test_intranet_override_without_marker_warns(self, monkeypatch) -> None:
        """内网开放覆盖文件清空回环标记后，非回环监听且无 Token 必须告警。"""
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("0.0.0.0")
        assert any("非回环" in c and "ARGUS_API_TOKEN" in c for c in calls)

    def test_bare_metal_source_work_dir_still_warns(self, monkeypatch) -> None:
        """裸机用户即使设置了 source work dir，只要没回环标记/Token 仍应告警。"""
        monkeypatch.setenv("ARGUS_WHITEBOX_SOURCE_WORK_DIR", "/tmp/sources")
        calls = self._capture_warns(monkeypatch)
        _warn_exposed_without_auth("0.0.0.0")
        assert any("非回环" in c and "ARGUS_API_TOKEN" in c for c in calls)


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
