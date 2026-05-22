"""验证 CLI `argus serve` 多 worker 拒启护栏与 lifespan 兜底告警。

私网部署常见误操作：K8s replicas 调大、env 设 WEB_CONCURRENCY、
直接 ``uvicorn ... --workers N``。当前 Argus 用进程内队列 / EventBus，
多副本会导致任务双发与 WS 事件丢失，必须显式拦住。
"""

from __future__ import annotations

import importlib

import pytest
from argus_py.api.app import _warn_if_multi_worker
from argus_py.cli.commands.serve import _detect_multi_worker_env

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
