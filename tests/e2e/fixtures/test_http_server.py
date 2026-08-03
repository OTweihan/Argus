"""E2E 测试 fixtures：本地 HTTP 测试服务器。

提供 ThreadingHTTPServer + BaseHTTPRequestHandler：
- Server A：页面 + 同源 API（固定路径、响应码）
- Server B：不同随机端口，模拟跨域 origin
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def _find_free_port() -> int:
    """返回一个可用端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _TestPageHandler(BaseHTTPRequestHandler):
    """返回测试页面和同源 API 端点。"""

    # 类变量，子类化时覆盖
    worker_js: str = ""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._serve_page()
        elif self.path == "/worker.js":
            self._serve_worker()
        elif self.path.startswith("/api/"):
            self._serve_api()
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._serve_api()
        else:
            self.send_error(404)

    def _serve_page(self) -> None:
        html = """<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
<h1>Argus E2E Test</h1>
<div id="output"></div>
<script>
// 发起 fetch/XHR 请求供 BrowserContext 捕获
fetch('/api/users');
fetch('/api/orders/42');
</script>
</body>
</html>"""
        self._send_response(200, html.encode(), "text/html")

    def _serve_worker(self) -> None:
        """Service Worker 脚本。"""
        js = (
            self.worker_js
            or """
self.addEventListener('fetch', (event) => {
    // 匹配 /api/cached 时从缓存返回
    if (event.request.url.includes('/api/cached')) {
        event.respondWith(
            caches.match(event.request).then((r) => r || fetch(event.request))
        );
    }
});
"""
        )
        self._send_response(200, js.encode(), "application/javascript")

    def _serve_api(self) -> None:
        data = {"path": self.path, "method": self.command, "status": "ok"}
        self._send_response(200, json.dumps(data).encode(), "application/json")

    def _send_response(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """静默日志（测试中不需要）"""
        pass


class TestHttpServer:
    """本地测试 HTTP 服务器上下文管理器。"""

    def __init__(self, handler_class: type = _TestPageHandler) -> None:
        self._port = _find_free_port()
        self._server = HTTPServer(("127.0.0.1", self._port), handler_class)
        self._thread: threading.Thread | None = None
        self.url = f"http://127.0.0.1:{self._port}"

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> TestHttpServer:
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


def create_test_servers() -> tuple[TestHttpServer, TestHttpServer]:
    """创建 Server A（同源）和 Server B（跨域）。"""
    server_a = TestHttpServer()
    server_b = TestHttpServer()
    return server_a, server_b
