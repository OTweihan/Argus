"""Java 白盒分析子模块客户端占位。"""

from __future__ import annotations


class WhiteboxClient:
    """第三阶段接入 Java 分析服务。"""

    def __init__(self, base_url: str = "http://localhost:8081") -> None:
        self.base_url = base_url.rstrip("/")
