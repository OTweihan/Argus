"""Prompt 模板加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus_py.core.paths import BUILTIN_PROMPTS_DIR


@dataclass(frozen=True)
class PromptTemplate:
    """内置 Prompt 模板。"""

    name: str
    content: str
    source: str = "unknown"

    def render(self, **kwargs: Any) -> str:
        """替换 {{name}} 和 {{ name }} 形式的占位符。"""
        rendered = self.content
        for key, value in kwargs.items():
            text = str(value)
            rendered = rendered.replace("{{" + key + "}}", text)
            rendered = rendered.replace("{{ " + key + " }}", text)
        return rendered


def resolve_prompt_path(
    name: str,
    builtin_prompts_dir: str | Path = BUILTIN_PROMPTS_DIR,
) -> Path:
    """解析内置 Prompt 文件路径；用户自定义已改为 project/task 级 parameters 注入。"""
    path = Path(name)
    if path.exists():
        return path
    return Path(builtin_prompts_dir) / name


def load_prompt_template(
    name: str,
    builtin_prompts_dir: str | Path = BUILTIN_PROMPTS_DIR,
) -> PromptTemplate:
    """读取 Prompt 模板对象。"""
    path = resolve_prompt_path(name, builtin_prompts_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {name} (builtin_dir={Path(builtin_prompts_dir)})"
        )
    return PromptTemplate(
        name=path.name, content=path.read_text(encoding="utf-8"), source=str(path)
    )


def load_prompt(
    name: str,
    builtin_prompts_dir: str | Path = BUILTIN_PROMPTS_DIR,
) -> str:
    """读取 Prompt 模板文本。"""
    return load_prompt_template(name, builtin_prompts_dir).content


def render_prompt(
    name: str,
    builtin_prompts_dir: str | Path = BUILTIN_PROMPTS_DIR,
    **kwargs: Any,
) -> str:
    """读取并渲染 Prompt。"""
    return load_prompt_template(name, builtin_prompts_dir).render(**kwargs)
