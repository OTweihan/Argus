"""校验 ``.env.example`` 与代码常量保持一致。

诊断背景：早先 ``.env.example`` 只覆盖了部分 env，并且常量值与示例之间没有
任何约束 —— 改了 ``DEFAULT_*`` 常量后示例不会被同步更新，长期跑下来就会
出现"代码默认 20、示例写 30"的漂移。

本测试做两件事：

1. 列出 ``.env.example`` 中所有未注释、有显式赋值的 key；
2. 对每个有对应代码默认值的 key，把代码常量归一化为字符串后断言相等。

发版时若有人改了 ``DEFAULT_MAX_STEPS`` 但忘了改 ``.env.example``，CI 会立即报错。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argus_py.config.server_settings import ServerSettings
from argus_py.core.constants import (
    DEFAULT_BROWSER,
    DEFAULT_HEADLESS,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_STEPS,
    DEFAULT_TASK_TIMEOUT_S,
)

ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / ".env.example"


def _parse_env_example(text: str) -> dict[str, str]:
    """把 ``.env.example`` 当作 ``KEY=VALUE`` 文件解析，忽略空行与 ``#`` 注释。

    注意 dotenv 真实语法支持 quote / 多行 / export 前缀等，本项目示例文件
    只用最简形式，因此这里实现一个极简解析器即可；若未来 .env.example 出现
    更复杂语法，请改用 ``python-dotenv`` 的 ``dotenv_values``。
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


@pytest.fixture(scope="module")
def env_example() -> dict[str, str]:
    """加载并解析 ``.env.example``。"""
    assert ENV_EXAMPLE_PATH.exists(), f".env.example 不存在：{ENV_EXAMPLE_PATH}"
    return _parse_env_example(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"))


def test_env_example_contains_all_expected_keys(env_example: dict[str, str]) -> None:
    """显式覆盖的 key 必须全部存在。注释掉的高级开关不在此列。"""
    expected = {
        "BROWSER_HEADLESS",
        "BROWSER_TYPE",
        "MAX_STEPS",
        "TASK_TIMEOUT_S",
        "OUTPUT_DIR",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TRACE_ENABLED",
        "LLM_TRACE_MAX_SIZE_MB",
        "LLM_TRACE_CONTENT_REDACT",
    }
    missing = expected - set(env_example)
    assert not missing, f".env.example 缺少必填示例项：{sorted(missing)}"


@pytest.mark.parametrize(
    ("env_key", "expected"),
    [
        ("BROWSER_HEADLESS", str(DEFAULT_HEADLESS).lower()),
        ("BROWSER_TYPE", DEFAULT_BROWSER),
        ("MAX_STEPS", str(DEFAULT_MAX_STEPS)),
        ("TASK_TIMEOUT_S", str(DEFAULT_TASK_TIMEOUT_S)),
        ("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        ("LLM_MODEL", DEFAULT_LLM_MODEL),
    ],
    ids=[
        "BROWSER_HEADLESS",
        "BROWSER_TYPE",
        "MAX_STEPS",
        "TASK_TIMEOUT_S",
        "LLM_BASE_URL",
        "LLM_MODEL",
    ],
)
def test_env_example_matches_constants(
    env_example: dict[str, str], env_key: str, expected: str
) -> None:
    """.env.example 中的展示值必须与 ``constants.py`` 中的 DEFAULT_* 严格一致。"""
    actual = env_example[env_key]
    assert actual == expected, (
        f".env.example[{env_key}] = {actual!r}，但代码常量默认值是 {expected!r}。\n"
        "若新值是有意为之，请同步修改另一处；否则恢复为代码常量值。"
    )


@pytest.mark.parametrize(
    ("env_key", "expected"),
    [
        ("LLM_TRACE_ENABLED", str(ServerSettings.llm_trace_enabled).lower()),
        ("LLM_TRACE_MAX_SIZE_MB", str(ServerSettings.llm_trace_max_size_mb)),
        ("LLM_TRACE_CONTENT_REDACT", str(ServerSettings.llm_trace_content_redact).lower()),
    ],
    ids=["LLM_TRACE_ENABLED", "LLM_TRACE_MAX_SIZE_MB", "LLM_TRACE_CONTENT_REDACT"],
)
def test_env_example_matches_server_settings(
    env_example: dict[str, str], env_key: str, expected: str
) -> None:
    """LLM Trace 相关 env 不在 ``constants.py`` 里，默认值来自 ``ServerSettings``。

    这里直接读 dataclass 的字段默认值，避免在测试里硬编码 50 / true 这种"
    "魔法数字。
    """
    actual = env_example[env_key]
    assert (
        actual == expected
    ), f".env.example[{env_key}] = {actual!r}，但 ServerSettings 默认值是 {expected!r}。"


def test_env_example_api_key_is_placeholder(env_example: dict[str, str]) -> None:
    """``LLM_API_KEY`` 是必填项，example 中应留空或仅给占位，避免被复制粘贴成
    真实 key 误提交 —— 任何包含 ``sk-``/``key-`` 等疑似真实 key 的内容都拒绝。"""
    value = env_example["LLM_API_KEY"]
    # 允许空、或明显是占位（your-key / changeme 等）
    if value == "":
        return
    lowered = value.lower()
    suspicious = ("sk-", "key-", "tk-")
    assert not any(
        lowered.startswith(p) for p in suspicious
    ), f".env.example[LLM_API_KEY] 不应包含真实 key（值={value!r}）。"


def test_env_example_output_dir_is_relative(env_example: dict[str, str]) -> None:
    """``OUTPUT_DIR`` 在 example 中应保持为相对路径，避免把开发机绝对路径泄露
    出去，也方便其它人直接 copy 到自己机器。"""
    value = env_example["OUTPUT_DIR"]
    path = Path(value)
    assert (
        not path.is_absolute()
    ), f".env.example[OUTPUT_DIR] 应为相对路径，但实际是绝对路径：{value!r}。"
    assert value == "outputs", f".env.example[OUTPUT_DIR] 习惯写法为 'outputs'，当前是 {value!r}。"
