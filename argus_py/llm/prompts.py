"""Prompt template loading."""

import os
from pathlib import Path

from argus_py.core.constants import DEFAULT_PROMPTS_DIR


def load_prompt(name: str, prompts_dir: str = DEFAULT_PROMPTS_DIR) -> str:
    """Load a prompt template from the prompts directory.

    Args:
        name: Template filename (e.g. "blackbox_planner.md").
        prompts_dir: Directory containing prompt templates.

    Returns:
        Prompt template text.

    Raises:
        FileNotFoundError: If template not found.
    """
    path = Path(prompts_dir) / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")
