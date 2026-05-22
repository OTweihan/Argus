"""验证 ModelConfigService 在 create / update / test 三处入口都拦截 SSRF。

私网部署语境下，攻击者可能：
- 直接创建一个 base_url 指向 ``http://10.x.x.x`` 的模型配置（绕过 /test）
- 把已有模型配置 update 到内网 IP
- 用 /test 在不落库的情况下探测内网

这三个口子必须都拦住，且默认放行 localhost（Ollama 同机场景）。
"""

from __future__ import annotations

import pytest
from argus_py.config.model_storage import ModelConfigSQLiteStorage
from argus_py.config.server_settings import ServerSettings
from argus_py.config.service import ModelConfigService
from argus_py.core.exceptions import ModelConfigError


@pytest.fixture
def service(tmp_path) -> ModelConfigService:
    """构造隔离的 ModelConfigService（独立 SQLite）。"""
    return ModelConfigService(ModelConfigSQLiteStorage(tmp_path / "models.db"))


@pytest.fixture(autouse=True)
def _empty_allow_hosts(monkeypatch) -> None:
    """覆盖 server settings，确保用例不依赖项目根 config/server.yaml。"""
    monkeypatch.setattr(
        "argus_py.config.service.load_server_settings",
        lambda: ServerSettings(llm_allow_private_hosts=[]),
    )


class TestCreateBlocksSSRF:
    def test_rejects_private_ip(self, service: ModelConfigService) -> None:
        with pytest.raises(ModelConfigError, match="内网/特殊地址"):
            service.create_model_config(
                name="probe",
                provider="custom",
                model="dummy",
                api_key="sk-x",
                base_url="http://10.0.0.5:8000/v1",
            )

    def test_rejects_metadata(self, service: ModelConfigService) -> None:
        with pytest.raises(ModelConfigError, match="metadata"):
            service.create_model_config(
                name="probe",
                provider="custom",
                model="dummy",
                api_key="sk-x",
                base_url="http://169.254.169.254/latest/meta-data/",
            )

    def test_allows_localhost(self, service: ModelConfigService) -> None:
        """同机 Ollama 这类常见场景不应被拦。"""
        config = service.create_model_config(
            name="ollama",
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434/v1",
        )
        assert config.base_url == "http://localhost:11434/v1"

    def test_allows_public(self, service: ModelConfigService) -> None:
        config = service.create_model_config(
            name="oa",
            provider="openai",
            model="gpt-4",
            api_key="sk-x",
            base_url="https://api.openai.com/v1",
        )
        assert config.base_url == "https://api.openai.com/v1"


class TestUpdateBlocksSSRF:
    def test_update_rejects_private_ip(self, service: ModelConfigService) -> None:
        config = service.create_model_config(
            name="oa",
            provider="openai",
            model="gpt-4",
            api_key="sk-x",
            base_url="https://api.openai.com/v1",
        )
        with pytest.raises(ModelConfigError, match="内网/特殊地址"):
            service.update_model_config(
                config.model_config_id,
                {"base_url": "http://192.168.1.100:8000/v1"},
            )


class TestAllowHostsBypass:
    def test_create_allowed_via_whitelist(self, service: ModelConfigService, monkeypatch) -> None:
        """配置了 allow_private_hosts 的内网 LLM 应能创建。"""
        monkeypatch.setattr(
            "argus_py.config.service.load_server_settings",
            lambda: ServerSettings(llm_allow_private_hosts=["10.10.20.5"]),
        )
        config = service.create_model_config(
            name="internal-llm",
            provider="custom",
            model="qwen-72b",
            api_key="sk-x",
            base_url="http://10.10.20.5:8000/v1",
        )
        assert config.base_url == "http://10.10.20.5:8000/v1"


class TestSettingsLoadFailureIsSafe:
    def test_failed_settings_uses_empty_allowlist(
        self, service: ModelConfigService, monkeypatch
    ) -> None:
        """settings 读取失败时 fallback 为空白名单（拒绝内网，安全默认）。"""

        def _boom() -> ServerSettings:
            raise RuntimeError("yaml broken")

        monkeypatch.setattr("argus_py.config.service.load_server_settings", _boom)
        with pytest.raises(ModelConfigError, match="内网/特殊地址"):
            service.create_model_config(
                name="probe",
                provider="custom",
                model="dummy",
                api_key="sk-x",
                base_url="http://10.0.0.5:8000/v1",
            )
