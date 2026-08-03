"""白盒类型化配置单元测试。

覆盖 ``WhiteboxTaskConfig`` 和 ``WhiteboxMavenConfig`` 的字段级校验。
"""

from __future__ import annotations

import pytest
from argus_py.whitebox.config import (
    ClasspathMode,
    SourceType,
    WhiteboxMavenConfig,
    WhiteboxTaskConfig,
    _sanitize_repo_url_for_display,
    validate_git_url,
)
from pydantic import ValidationError

# ═══════════════════════════════════════════════════════════════════════════════
# validate_git_url
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/user/repo.git",
        "http://gitlab.internal/group/project.git",
        "ssh://git@github.com:org/repo.git",
        "git@github.com:org/repo.git",
    ],
)
def test_validate_git_url_accepts_valid(url: str) -> None:
    """合法的 https/http/ssh/scp 风格 URL 应通过。"""
    assert validate_git_url(url) == url


def test_validate_git_url_none_passes_through() -> None:
    """None 输入直接透传。"""
    assert validate_git_url(None) is None


@pytest.mark.parametrize(
    ("url", "expected_substr"),
    [
        ("file:///etc/passwd", "仅支持"),
        ("ftp://host/repo.git", "仅支持"),
        ("https://user:password@github.com/user/repo.git", "内嵌"),
        ("https://token@github.com/user/repo.git", "内嵌"),
        ("https://github.com/user/repo.git?token=abc123", "query"),
        ("https://github.com/user/repo.git?access_token=abc", "query"),
        ("https://github.com/user/repo.git?private_token=abc", "query"),
        ("https://github.com/user/repo.git?password=secret", "query"),
        ("https://github.com/user/repo.git?secret=value", "query"),
    ],
)
def test_validate_git_url_rejects_dangerous(url: str, expected_substr: str) -> None:
    """危险 URL 应拒绝并包含预期的错误描述。"""
    with pytest.raises(ValueError, match=expected_substr):
        validate_git_url(url)


# ═══════════════════════════════════════════════════════════════════════════════
# _sanitize_repo_url_for_display
# ═══════════════════════════════════════════════════════════════════════════════


def test_sanitize_url_strips_userinfo() -> None:
    """带 userinfo 的 https URL 脱敏后移除 user:pass 部分。"""
    result = _sanitize_repo_url_for_display("https://user:token@github.com/org/repo.git")
    assert result == "https://github.com/org/repo.git"


def test_sanitize_url_scp_style() -> None:
    """scp 风格 URL 脱敏后移除 git@ 部分。"""
    result = _sanitize_repo_url_for_display("git@github.com:org/repo.git")
    assert result == "github.com:org/repo.git"


def test_sanitize_url_none_passes_through() -> None:
    """None 直接透传。"""
    assert _sanitize_repo_url_for_display(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# WhiteboxMavenConfig
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhiteboxMavenConfig:
    """Maven 配置模型校验。"""

    def test_defaults(self) -> None:
        """默认值应与 Java 端对齐。"""
        cfg = WhiteboxMavenConfig()
        assert cfg.auto_detect is True
        assert cfg.generate_classpath is True
        assert cfg.offline is False
        assert cfg.classpath_mode == ClasspathMode.AUTO
        assert cfg.classpath_file is None
        assert cfg.executable is None
        assert cfg.settings_xml is None
        assert cfg.local_repository is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("auto", "AUTO"),
            ("AUTO", "AUTO"),
            ("cache-only", "CACHE_ONLY"),
            ("CACHE_ONLY", "CACHE_ONLY"),
            ("maven", "MAVEN"),
            ("MAVEN", "MAVEN"),
            ("source-only", "SOURCE_ONLY"),
            ("SOURCE_ONLY", "SOURCE_ONLY"),
        ],
    )
    def test_classpath_mode_normalization(self, raw: str, expected: str) -> None:
        """连字符格式与大小写统一规范化为 Java ClasspathMode 枚举格式。"""
        cfg = WhiteboxMavenConfig(classpath_mode=raw)  # type: ignore[arg-type]
        assert cfg.classpath_mode == expected

    def test_classpath_mode_rejects_unknown(self) -> None:
        """未知值由 ClasspathMode enum 直接拒绝。"""
        with pytest.raises(ValidationError):
            WhiteboxMavenConfig(classpath_mode="custom-mode")  # type: ignore[arg-type]

    def test_offline_timeout_bounds(self) -> None:
        """offline_timeout_seconds 范围 [1, 3600]。"""
        with pytest.raises(ValidationError):
            WhiteboxMavenConfig(offline_timeout_seconds=0)
        with pytest.raises(ValidationError):
            WhiteboxMavenConfig(offline_timeout_seconds=3601)
        # 边界值应通过
        cfg = WhiteboxMavenConfig(offline_timeout_seconds=1)
        assert cfg.offline_timeout_seconds == 1
        cfg = WhiteboxMavenConfig(offline_timeout_seconds=3600)
        assert cfg.offline_timeout_seconds == 3600

    def test_online_timeout_bounds(self) -> None:
        """online_timeout_seconds 范围 [1, 7200]。"""
        with pytest.raises(ValidationError):
            WhiteboxMavenConfig(online_timeout_seconds=0)
        with pytest.raises(ValidationError):
            WhiteboxMavenConfig(online_timeout_seconds=7201)

    def test_camelcase_alias(self) -> None:
        """camelCase 字段名通过 alias 正确映射。"""
        cfg = WhiteboxMavenConfig.model_validate(
            {
                "autoDetect": False,
                "classpathFile": "target/classpath.txt",
                "settingsXml": "/path/to/settings.xml",
                "localRepository": "/path/to/repo",
                "classpathMode": "MAVEN",
                "offlineTimeoutSeconds": 120,
                "onlineTimeoutSeconds": 600,
                "prepareReactorArtifacts": True,
            }
        )
        assert cfg.auto_detect is False
        assert cfg.classpath_file == "target/classpath.txt"
        assert cfg.settings_xml == "/path/to/settings.xml"
        assert cfg.local_repository == "/path/to/repo"
        assert cfg.classpath_mode == "MAVEN"
        assert cfg.offline_timeout_seconds == 120
        assert cfg.online_timeout_seconds == 600
        assert cfg.prepare_reactor_artifacts is True


# ═══════════════════════════════════════════════════════════════════════════════
# WhiteboxTaskConfig
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhiteboxTaskConfigSourceType:
    """source_type 互斥校验。"""

    def test_local_default(self) -> None:
        """不指定 source_type 时默认为 local。"""
        cfg = WhiteboxTaskConfig(source_path="/tmp/project")
        assert cfg.source_type == SourceType.LOCAL

    def test_git_requires_repo_url(self) -> None:
        """source_type=git 时 repo_url 为必填。"""
        with pytest.raises(ValidationError, match="repo_url"):
            WhiteboxTaskConfig(source_type=SourceType.GIT)

    def test_git_rejects_source_path(self) -> None:
        """source_type=git 时不能同时提供 source_path。"""
        with pytest.raises(ValidationError, match="source_path"):
            WhiteboxTaskConfig(
                source_type=SourceType.GIT,
                repo_url="https://github.com/user/repo.git",
                source_path="/tmp/project",
            )

    def test_local_requires_source_path(self) -> None:
        """source_type=local 时 source_path 为必填。"""
        with pytest.raises(ValidationError, match="source_path"):
            WhiteboxTaskConfig(source_type=SourceType.LOCAL)

    def test_local_rejects_repo_url(self) -> None:
        """source_type=local 时不能同时提供 repo_url。"""
        with pytest.raises(ValidationError, match="repo_url"):
            WhiteboxTaskConfig(
                source_type=SourceType.LOCAL,
                source_path="/tmp/project",
                repo_url="https://github.com/user/repo.git",
            )

    def test_local_rejects_ref(self) -> None:
        """source_type=local 时不能提供 ref。"""
        with pytest.raises(ValidationError, match="ref"):
            WhiteboxTaskConfig(
                source_type=SourceType.LOCAL,
                source_path="/tmp/project",
                ref="main",
            )

    def test_modules_scope_requires_target_modules(self) -> None:
        """scope=modules 时 target_modules 不能为空。"""
        with pytest.raises(ValidationError, match="target_modules"):
            WhiteboxTaskConfig(
                source_path="/tmp/project",
                scope="modules",
            )

    def test_modules_scope_with_target_modules_passes(self) -> None:
        """scope=modules + target_modules 非空应通过。"""
        cfg = WhiteboxTaskConfig(
            source_path="/tmp/project",
            scope="modules",
            target_modules=["module-a", "module-b"],
        )
        assert cfg.scope == "modules"
        assert cfg.target_modules == ["module-a", "module-b"]

    @pytest.mark.parametrize(
        "scope", ["all", "changed", "endpoints", "callgraph", "flows", "clusters"]
    )
    def test_valid_scopes(self, scope: str) -> None:
        """7 种 scope 值均应通过 pattern 校验。"""
        cfg = WhiteboxTaskConfig(source_path="/tmp/project", scope=scope)
        assert cfg.scope == scope

    def test_invalid_scope_rejected(self) -> None:
        """不在允许列表的 scope 应被拒绝。"""
        with pytest.raises(ValidationError):
            WhiteboxTaskConfig(source_path="/tmp/project", scope="unknown")


class TestWhiteboxTaskConfigTargetModules:
    """target_modules 字段校验。"""

    def test_deduplication(self) -> None:
        """重复模块名去重，保留首次出现顺序。"""
        cfg = WhiteboxTaskConfig(
            source_path="/tmp/project",
            target_modules=["a", "b", "a", "c", "b"],
        )
        assert cfg.target_modules == ["a", "b", "c"]

    def test_blank_filtered(self) -> None:
        """空白字符串被过滤。"""
        cfg = WhiteboxTaskConfig(
            source_path="/tmp/project",
            target_modules=["  ", "a", "", "b", "\t"],
        )
        assert cfg.target_modules == ["a", "b"]

    def test_item_too_long_rejected(self) -> None:
        """单个模块名超过 256 字符应拒绝。"""
        with pytest.raises(ValidationError, match="过长"):
            WhiteboxTaskConfig(
                source_path="/tmp/project",
                target_modules=["a" * 257],
            )

    def test_max_100_items(self) -> None:
        """最多 100 个模块。"""
        modules = [f"m{i}" for i in range(100)]
        cfg = WhiteboxTaskConfig(source_path="/tmp/project", target_modules=modules)
        assert len(cfg.target_modules) == 100

    def test_more_than_100_rejected(self) -> None:
        """超过 100 个模块应拒绝。"""
        with pytest.raises(ValidationError):
            WhiteboxTaskConfig(
                source_path="/tmp/project",
                target_modules=[f"m{i}" for i in range(101)],
            )


class TestWhiteboxTaskConfigRepoUrl:
    """repo_url 安全校验。"""

    def test_rejects_file_scheme(self) -> None:
        """file:// 协议应拒绝。"""
        with pytest.raises(ValidationError, match="仅支持"):
            WhiteboxTaskConfig(
                source_type=SourceType.GIT,
                repo_url="file:///etc/passwd",
            )

    def test_rejects_embedded_credentials(self) -> None:
        """内嵌 user:password 应拒绝。"""
        with pytest.raises(ValidationError, match="内嵌"):
            WhiteboxTaskConfig(
                source_type=SourceType.GIT,
                repo_url="https://alice:secret@github.com/org/repo.git",
            )

    def test_rejects_token_in_username(self) -> None:
        """用户名含 token 应拒绝。"""
        with pytest.raises(ValidationError, match="内嵌"):
            WhiteboxTaskConfig(
                source_type=SourceType.GIT,
                repo_url="https://token@github.com/org/repo.git",
            )

    def test_rejects_token_in_query(self) -> None:
        """query 参数含 token 应拒绝。"""
        with pytest.raises(ValidationError, match="query"):
            WhiteboxTaskConfig(
                source_type=SourceType.GIT,
                repo_url="https://github.com/org/repo.git?access_token=secret123",
            )

    def test_accepts_scp_style(self) -> None:
        """git@host:path 风格 URL 应通过。"""
        cfg = WhiteboxTaskConfig(
            source_type=SourceType.GIT,
            repo_url="git@github.com:org/repo.git",
        )
        assert cfg.repo_url == "git@github.com:org/repo.git"


class TestWhiteboxTaskConfigCamelcase:
    """camelCase alias 映射。"""

    def test_full_camelcase_parse(self) -> None:
        """完整 camelCase JSON 输入应正确解析。"""
        cfg = WhiteboxTaskConfig.model_validate(
            {
                "sourceType": "git",
                "repoUrl": "https://github.com/user/repo.git",
                "ref": "main",
                "scope": "callgraph",
                "targetModules": ["core", "api"],
                "maven": {
                    "classpathMode": "MAVEN",
                    "offlineTimeoutSeconds": 300,
                },
            }
        )
        assert cfg.source_type == SourceType.GIT
        assert cfg.repo_url == "https://github.com/user/repo.git"
        assert cfg.ref == "main"
        assert cfg.scope == "callgraph"
        assert cfg.target_modules == ["core", "api"]
        assert cfg.maven is not None
        assert cfg.maven.classpath_mode == "MAVEN"
        assert cfg.maven.offline_timeout_seconds == 300


class TestWhiteboxTaskConfigToPersisted:
    """to_persisted() 转换。"""

    def test_clone_url_vs_display_url(self) -> None:
        """clone_url 保留原始 URL，source_repo_url 脱敏用于审计。"""
        cfg = WhiteboxTaskConfig(
            source_type=SourceType.GIT,
            repo_url="https://github.com/org/repo.git",
        )
        persisted = cfg.to_persisted()
        assert persisted.schema_version == 1
        assert persisted.clone_url == "https://github.com/org/repo.git"
        assert persisted.source_repo_url == "https://github.com/org/repo.git"

    def test_git_with_ref(self) -> None:
        """带分支引用的 Git 配置转换。"""
        cfg = WhiteboxTaskConfig(
            source_type=SourceType.GIT,
            repo_url="https://github.com/org/repo.git",
            ref="feature/x",
            scope="endpoints",
            target_modules=["mod"],
        )
        persisted = cfg.to_persisted()
        assert persisted.source_type == SourceType.GIT
        assert persisted.ref == "feature/x"
        assert persisted.scope == "endpoints"
        assert persisted.target_modules == ["mod"]

    def test_local_with_maven(self) -> None:
        """本地源码 + Maven 配置转换。"""
        cfg = WhiteboxTaskConfig(
            source_type=SourceType.LOCAL,
            source_path="/home/user/project",
            maven=WhiteboxMavenConfig(
                classpath_mode=ClasspathMode.CACHE_ONLY,
                offline=True,
            ),
        )
        persisted = cfg.to_persisted()
        assert persisted.source_type == SourceType.LOCAL
        assert persisted.source_path == "/home/user/project"
        assert persisted.maven is not None
        assert persisted.maven.classpath_mode == ClasspathMode.CACHE_ONLY
        assert persisted.maven.offline is True

    def test_to_execution_config_roundtrip(self) -> None:
        """persisted → execution 转换保留关键字段。"""
        cfg = WhiteboxTaskConfig(
            source_type=SourceType.LOCAL,
            source_path="/tmp/proj",
            scope="all",
        )
        exec_cfg = cfg.to_persisted().to_execution_config()
        assert exec_cfg.source_type == SourceType.LOCAL
        assert exec_cfg.source_path == "/tmp/proj"
        assert exec_cfg.scope == "all"

    def test_to_execution_config_git(self) -> None:
        """Git 配置的 persisted → execution 转换使用 clone_url。"""
        cfg = WhiteboxTaskConfig(
            source_type=SourceType.GIT,
            repo_url="https://github.com/org/repo.git",
            ref="dev",
        )
        exec_cfg = cfg.to_persisted().to_execution_config()
        assert exec_cfg.source_type == SourceType.GIT
        assert exec_cfg.repo_url == "https://github.com/org/repo.git"
        assert exec_cfg.ref == "dev"


class TestWhiteboxTaskConfigFromLegacy:
    """from_legacy_parameters() 兼容旧参数字典。"""

    def test_git_legacy(self) -> None:
        """旧格式 Git 参数字典应正确解析。"""
        cfg = WhiteboxTaskConfig.from_legacy_parameters(
            {
                "repo_url": "https://github.com/user/repo.git",
                "branch": "develop",
                "scope": "callgraph",
                "target_modules": ["x"],
            }
        )
        assert cfg.source_type == SourceType.GIT
        assert cfg.repo_url == "https://github.com/user/repo.git"
        assert cfg.ref == "develop"
        assert cfg.scope == "callgraph"

    def test_local_legacy(self) -> None:
        """旧格式本地源码参数字典应正确解析。"""
        cfg = WhiteboxTaskConfig.from_legacy_parameters(
            {
                "source_path": "/home/dev/project",
                "scope": "endpoints",
            }
        )
        assert cfg.source_type == SourceType.LOCAL
        assert cfg.source_path == "/home/dev/project"
        assert cfg.scope == "endpoints"

    def test_legacy_with_maven(self) -> None:
        """旧格式包含 maven 配置应正确解析。"""
        cfg = WhiteboxTaskConfig.from_legacy_parameters(
            {
                "source_path": "/project",
                "scope": "all",
                "maven": {
                    "classpathMode": "MAVEN",
                    "offline": True,
                },
            }
        )
        assert cfg.maven is not None
        assert cfg.maven.classpath_mode == "MAVEN"
        assert cfg.maven.offline is True

    def test_legacy_defaults(self) -> None:
        """旧格式最小参数字典使用合理默认值。"""
        cfg = WhiteboxTaskConfig.from_legacy_parameters(
            {
                "source_path": "/project",
            }
        )
        assert cfg.scope == "all"
        assert cfg.target_modules == []
        assert cfg.maven is None

    def test_legacy_empty_dict(self) -> None:
        """旧格式空字典 → 应给出明确错误（source_path 必填）。"""
        with pytest.raises(ValidationError):
            WhiteboxTaskConfig.from_legacy_parameters({})

    def test_legacy_with_maven_none(self) -> None:
        """旧格式含 maven=None → 不抛 TypeError。"""
        cfg = WhiteboxTaskConfig.from_legacy_parameters(
            {
                "source_path": "/project",
                "maven": None,
            }
        )
        assert cfg.maven is None

    def test_persisted_to_execution_scope_all(self) -> None:
        """scope=all 时 to_execution_config 正确转换。"""
        cfg = WhiteboxTaskConfig(source_type=SourceType.LOCAL, source_path="/tmp/p", scope="all")
        exec_cfg = cfg.to_persisted().to_execution_config()
        assert exec_cfg.scope == "all"

    def test_persisted_to_execution_maven_none(self) -> None:
        """maven 为 None 时 to_execution_config 不崩溃。"""
        cfg = WhiteboxTaskConfig(source_type=SourceType.LOCAL, source_path="/tmp/p")
        exec_cfg = cfg.to_persisted().to_execution_config()
        assert exec_cfg.maven is None
