"""LLM endpoint URL 安全校验（SSRF 防御）。

私网部署语境下，``/config/models/test`` 等入口接受用户指定的 ``base_url``
后立即发起 outbound 请求，会成为 SSRF 攻击面：可探测云 metadata
(``169.254.169.254``)、内部 admin 后台、其他内部 API。

本模块专门针对 LLM endpoint URL 做加固，与 :mod:`argus_py.browser.url_validator`
区分开 —— 后者服务于 agent 的浏览器导航目标，本来就允许内网（爬虫场景）。

策略（默认）：
- 必须是 http/https
- 拒绝云 metadata 主机
- 拒绝 RFC1918 私网（``10/8``、``172.16/12``、``192.168/16``）、链路本地、
  保留段、组播
- 默认放行 ``localhost`` 与 ``127.0.0.1``（让本机 Ollama 这类常见场景开箱即用，
  且仅暴露给同机进程，攻击面有限）

放行白名单：
- 通过 ``allow_hosts`` 显式列出主机名/IP，例如内网自部署的 vLLM / Ollama 服务器。
  在 ``config/server.yaml`` 的 ``llm.allow_private_hosts`` 字段维护。
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlparse

_METADATA_HOSTS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)

_DEFAULT_LOCAL_ALLOWS: frozenset[str] = frozenset({"localhost", "127.0.0.1"})


class LLMUrlSafetyError(ValueError):
    """LLM endpoint URL 命中 SSRF deny list。"""


def assert_llm_base_url_safe(
    base_url: str | None,
    *,
    allow_hosts: Iterable[str] = (),
) -> None:
    """检查 LLM ``base_url`` 是否在允许范围内，命中则抛 ``LLMUrlSafetyError``。

    空字符串 / None 视为"未配置"，由调用方自行 fallback，不在本函数报错。

    ``allow_hosts`` 中的项支持 host 名称或 IP 字面量，匹配大小写不敏感。
    """
    if not base_url:
        return
    parsed = urlparse(base_url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise LLMUrlSafetyError(f"LLM base_url 必须使用 http/https：{base_url}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise LLMUrlSafetyError(f"LLM base_url 缺少主机名：{base_url}")

    allow_set = {item.strip().lower() for item in allow_hosts if item and item.strip()}
    if host in allow_set:
        return

    if host in _METADATA_HOSTS:
        raise LLMUrlSafetyError(
            f"禁止指向云 metadata 服务：{host}。"
            "如确为内部 LLM，请把该主机加入 config/server.yaml 的 llm.allow_private_hosts。"
        )

    if host in _DEFAULT_LOCAL_ALLOWS:
        return

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_private
        ):
            raise LLMUrlSafetyError(
                f"禁止指向内网/特殊地址：{host}。"
                "如确为内部 LLM，请把该 IP 加入 config/server.yaml 的 llm.allow_private_hosts。"
            )
        return

    if host.endswith(".local") or host.endswith(".internal"):
        raise LLMUrlSafetyError(
            f"禁止指向内网域名：{host}。"
            "如确为内部 LLM，请把该域名加入 config/server.yaml 的 llm.allow_private_hosts。"
        )
