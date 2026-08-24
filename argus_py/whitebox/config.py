"""白盒任务类型化配置模型。

API 层使用 ``WhiteboxTaskConfig``（继承 ApiModel，支持 camelCase）。
持久化层使用 ``PersistedWhiteboxConfig``（snake_case，含 schema 版本号）。
Worker 执行时使用 ``ExecutionWhiteboxConfig``（纯内存，含已验证的可执行 URL）。
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

if TYPE_CHECKING:
    from argus_py.task.models import Task

# ── 枚举 ──────────────────────────────────────────────────────────────────────


class SourceType(StrEnum):
    GIT = "git"
    LOCAL = "local"


class ClasspathMode(StrEnum):
    """Classpath 解析策略 — 与 Java ClasspathMode 对齐。"""

    AUTO = "AUTO"
    CACHE_ONLY = "CACHE_ONLY"
    MAVEN = "MAVEN"
    SOURCE_ONLY = "SOURCE_ONLY"


# ── 旧参数字段集合（用于新旧冲突检测） ──────────────────────────────────────

LEGACY_WHITEBOX_PARAM_KEYS = frozenset(
    {
        "repo_url",
        "source_path",
        "branch",
        "scope",
        "target_modules",
        "maven",
        "classpath_mode",
    }
)


# ── Git URL 安全校验 ─────────────────────────────────────────────────────────

_ALLOWED_GIT_SCHEMES = frozenset({"https", "http", "ssh"})


def validate_git_url(url: str | None) -> str | None:
    """校验 Git 仓库 URL 安全性。

    接受：https/http/ssh 协议、scp 风格 (git@host:path)。
    拒绝：file://、ext::、内嵌凭据、危险 fragment。
    不修改 URL 内容——只验证。
    """
    if url is None:
        return None

    # scp 风格：git@host:org/repo.git
    if "://" not in url and ":" in url and "@" in url and url.startswith("git@"):
        return url

    parsed = urlsplit(url)

    if parsed.scheme not in _ALLOWED_GIT_SCHEMES:
        raise ValueError(f"Git URL 仅支持 https/http/ssh/scp 协议，当前 scheme: {parsed.scheme}")

    # 拒绝内嵌凭据
    if parsed.username and parsed.password:
        raise ValueError("repo_url 不允许内嵌 user:password")
    if parsed.username and not parsed.password and "token" in parsed.username.lower():
        raise ValueError("repo_url 不允许内嵌 token")

    # 拒绝 query 中的凭据
    if parsed.query:
        danger_keys = {"token", "access_token", "private_token", "password", "secret"}
        for key in danger_keys:
            if key in parsed.query.lower():
                raise ValueError(f"repo_url 不允许在 query 中携带 {key}")

    return url


# ── 工具 ──────────────────────────────────────────────────────────────────────


def _sanitize_repo_url_for_display(url: str | None) -> str | None:
    """生成审计展示用的脱敏 URL。

    仅用于审计展示 (task.source_repo_url)，不用于 clone。
    移除 userinfo 部分。
    """
    if url is None:
        return None
    if "://" not in url and ":" in url and "@" in url:
        # scp style: git@host:org/repo → host:org/repo
        return url.split("@", 1)[-1] if "@" in url else url
    parsed = urlsplit(url)
    if parsed.hostname:
        return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
    return url


# ── API 层模型（camelCase 支持）───────────────────────────────────────────────

_WHITEBOX_MODEL_CONFIG = ConfigDict(populate_by_name=True, alias_generator=None)


class WhiteboxMavenConfig(BaseModel):
    """Maven 配置（与 Java 端 MavenConfig 对齐）。"""

    model_config = ConfigDict(populate_by_name=True)

    auto_detect: bool = Field(default=True, alias="autoDetect")
    generate_classpath: bool = Field(default=True, alias="generateClasspath")
    classpath_file: str | None = Field(default=None, alias="classpathFile")
    executable: str | None = None
    settings_xml: str | None = Field(default=None, alias="settingsXml")
    local_repository: str | None = Field(default=None, alias="localRepository")
    offline: bool = False
    classpath_mode: ClasspathMode = Field(default=ClasspathMode.AUTO, alias="classpathMode")
    offline_timeout_seconds: int | None = Field(
        default=None, ge=1, le=3600, alias="offlineTimeoutSeconds"
    )
    online_timeout_seconds: int | None = Field(
        default=None, ge=1, le=7200, alias="onlineTimeoutSeconds"
    )
    prepare_reactor_artifacts: bool = Field(default=False, alias="prepareReactorArtifacts")

    @field_validator("classpath_mode", mode="before")
    @classmethod
    def _normalize_classpath_mode(cls, v: object) -> object:
        """将 CLI 的连字符格式 (cache-only) 规范化为 Java 格式 (CACHE_ONLY)。"""
        if isinstance(v, str):
            normalized = v.upper().replace("-", "_")
            if normalized in {"AUTO", "CACHE_ONLY", "MAVEN", "SOURCE_ONLY"}:
                return normalized
        return v


class WhiteboxTaskConfig(BaseModel):
    """白盒任务类型化配置（API 层，支持 camelCase 输入）。"""

    model_config = ConfigDict(populate_by_name=True)

    source_type: SourceType = Field(default=SourceType.LOCAL, alias="sourceType")
    repo_url: str | None = Field(default=None, max_length=2048, alias="repoUrl")
    source_path: str | None = Field(default=None, max_length=4096, alias="sourcePath")
    ref: str | None = Field(default=None, max_length=256)
    scope: str = Field(
        default="all",
        pattern=r"^(all|changed|modules|endpoints|callgraph|flows|clusters)$",
    )
    target_modules: list[str] = Field(default_factory=list, max_length=100, alias="targetModules")
    maven: WhiteboxMavenConfig | None = None

    @field_validator("target_modules")
    @classmethod
    def _dedupe_and_clean(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in v:
            s = item.strip()
            if not s or s in seen:
                continue
            if len(s) > 256:
                raise ValueError(f"target_modules 单项过长: {s[:80]}...")
            seen.add(s)
            result.append(s)
        return result

    @field_validator("repo_url")
    @classmethod
    def _validate_repo_url(cls, v: str | None) -> str | None:
        return validate_git_url(v)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.source_type == SourceType.GIT:
            if not self.repo_url:
                raise ValueError("source_type=git 时 repo_url 为必填")
            if self.source_path is not None:
                raise ValueError("source_type=git 时不能提供 source_path")
        if self.source_type == SourceType.LOCAL:
            if not self.source_path:
                raise ValueError("source_type=local 时 source_path 为必填")
            if self.repo_url is not None:
                raise ValueError("source_type=local 时不能提供 repo_url")
            if self.ref is not None:
                raise ValueError("source_type=local 时不能提供 ref")
        if self.scope == "modules" and not self.target_modules:
            raise ValueError("scope=modules 时 target_modules 不能为空")
        return self

    def to_persisted(self) -> PersistedWhiteboxConfig:
        """转换为可持久化格式。"""
        # clone_url: 验证后的原始 URL（可用作 clone），display_url: 脱敏用于审计
        return PersistedWhiteboxConfig(
            schema_version=1,
            source_type=self.source_type,
            clone_url=self.repo_url,
            source_repo_url=_sanitize_repo_url_for_display(self.repo_url),
            source_path=self.source_path,
            ref=self.ref,
            scope=self.scope,
            target_modules=self.target_modules,
            maven=self.maven,
        )

    @classmethod
    def from_legacy_parameters(cls, params: dict) -> WhiteboxTaskConfig:
        """从旧 parameters dict 解析，走完整校验。"""
        maven_raw = params.get("maven")
        maven = WhiteboxMavenConfig(**maven_raw) if maven_raw else None
        repo_url = params.get("repo_url")
        source_type = SourceType.GIT if repo_url else SourceType.LOCAL
        return cls(
            source_type=source_type,
            repo_url=repo_url,
            source_path=params.get("source_path"),
            ref=params.get("branch"),
            scope=params.get("scope", "all"),
            target_modules=params.get("target_modules", []),
            maven=maven,
        )


# ── 持久化模型（snake_case，版本化）───────────────────────────────────────────


class PersistedWhiteboxConfig(BaseModel):
    """持久化格式的白盒配置。repo_url 已脱敏或不含凭据，clone_url 可执行。"""

    schema_version: int = 1
    source_type: SourceType
    clone_url: str | None = None  # 可执行的 clone URL
    source_repo_url: str | None = None  # 审计展示用脱敏 URL
    source_path: str | None = None
    ref: str | None = None
    scope: str = "all"
    target_modules: list[str] = Field(default_factory=list)
    maven: WhiteboxMavenConfig | None = None

    def to_execution_config(self) -> ExecutionWhiteboxConfig:
        """转为执行时纯内存配置。

        clone_url 或 source_path 将被 SourceResolver 使用。
        由 SourceResolver 负责 allowed_roots 校验。
        """
        repo_url: str | None = None
        source_path: str | None = None

        if self.source_type == SourceType.GIT and self.clone_url:
            repo_url = self.clone_url
        elif self.source_type == SourceType.LOCAL and self.source_path:
            source_path = self.source_path

        return ExecutionWhiteboxConfig(
            source_type=self.source_type,
            repo_url=repo_url,
            source_path=source_path,
            ref=self.ref,
            scope=self.scope,
            target_modules=self.target_modules,
            maven=self.maven,
        )


# ── 执行时模型（纯内存，不含持久化字段）──────────────────────────────────────


@dataclass
class ExecutionWhiteboxConfig:
    """执行时使用的白盒配置（纯内存，不含持久化元数据）。"""

    source_type: SourceType
    repo_url: str | None = None
    source_path: str | None = None
    ref: str | None = None
    scope: str = "all"
    target_modules: list[str] = dc_field(default_factory=list)
    maven: WhiteboxMavenConfig | None = None


# ── 任务配置恢复（runner 与 recovery 共用）───────────────────────────────────


def load_persisted_config(task: Task) -> PersistedWhiteboxConfig:
    """从任务记录还原持久化白盒配置。

    新格式 ``task.whitebox_config_json`` 优先；缺失时回退旧 ``parameters``
    dict 解析（走完整校验后转持久化格式）。runner 与 recovery 必须共用此
    实现，避免两处还原逻辑行为分化。
    """
    if task.whitebox_config_json:
        return PersistedWhiteboxConfig.model_validate_json(task.whitebox_config_json)
    return WhiteboxTaskConfig.from_legacy_parameters(task.parameters).to_persisted()


def load_execution_config(task: Task) -> ExecutionWhiteboxConfig:
    """从任务记录还原执行时白盒配置（见 :func:`load_persisted_config`）。"""
    return load_persisted_config(task).to_execution_config()
