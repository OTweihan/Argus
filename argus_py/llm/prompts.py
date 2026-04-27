"""Prompt 模板加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus_py.core.paths import PROMPTS_DIR


@dataclass(frozen=True)
class PromptTemplate:
    """本地 Prompt 模板。"""

    name: str
    content: str

    def render(self, **kwargs: Any) -> str:
        """替换 {{name}} 和 {{ name }} 形式的占位符。"""
        rendered = self.content
        for key, value in kwargs.items():
            text = str(value)
            rendered = rendered.replace("{{" + key + "}}", text)
            rendered = rendered.replace("{{ " + key + " }}", text)
        return rendered


def resolve_prompt_path(name: str, prompts_dir: str | Path = PROMPTS_DIR) -> Path:
    """解析 Prompt 文件路径。"""
    path = Path(name)
    if path.exists():
        return path
    return Path(prompts_dir) / name


def load_prompt_template(name: str, prompts_dir: str | Path = PROMPTS_DIR) -> PromptTemplate:
    """读取 Prompt 模板对象。"""
    path = resolve_prompt_path(name, prompts_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return PromptTemplate(name=path.name, content=path.read_text(encoding="utf-8"))


def load_prompt(name: str, prompts_dir: str | Path = PROMPTS_DIR) -> str:
    """读取 Prompt 模板文本。"""
    return load_prompt_template(name, prompts_dir).content


def render_prompt(name: str, prompts_dir: str | Path = PROMPTS_DIR, **kwargs: Any) -> str:
    """读取并渲染 Prompt。"""
    return load_prompt_template(name, prompts_dir).render(**kwargs)
