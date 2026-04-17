"""Configuration loading from environment and config files."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ArgusConfig:
    """Application configuration."""

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"

    # Browser
    browser_headless: bool = False
    browser_type: str = "chromium"

    # Task
    max_steps: int = 20
    task_timeout_s: int = 300

    # Storage
    output_dir: str = "outputs"

    @classmethod
    def from_env(cls) -> "ArgusConfig":
        """Load configuration from environment variables."""
        return cls(
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv(
                "LLM_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            llm_model=os.getenv("LLM_MODEL", "qwen-plus"),
            browser_headless=os.getenv("BROWSER_HEADLESS", "false").lower() == "true",
            browser_type=os.getenv("BROWSER_TYPE", "chromium"),
            max_steps=int(os.getenv("MAX_STEPS", "20")),
            task_timeout_s=int(os.getenv("TASK_TIMEOUT_S", "300")),
            output_dir=os.getenv("OUTPUT_DIR", "outputs"),
        )
