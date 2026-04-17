"""Application-wide constants."""

# Project info
PROJECT_NAME = "Argus"
PROJECT_VERSION = "0.1.0"
PROJECT_TAGLINE = "Every bug has nowhere to hide."

# File names / paths
DEFAULT_OUTPUT_DIR = "outputs"
DEFAULT_LOGS_DIR = "outputs/logs"
DEFAULT_SCREENSHOTS_DIR = "outputs/screenshots"
DEFAULT_REPORTS_DIR = "outputs/reports"
DEFAULT_TEMP_DIR = "outputs/temp"
DEFAULT_PROMPTS_DIR = "config/prompts"

# Browser defaults
DEFAULT_BROWSER = "chromium"
DEFAULT_HEADLESS = False
DEFAULT_ACTION_TIMEOUT_MS = 10000
DEFAULT_NAVIGATION_TIMEOUT_MS = 30000

# LLM defaults
DEFAULT_LLM_MODEL = "qwen-plus"
DEFAULT_LLM_MAX_TOKENS = 4096
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_RETRIES = 3

# Task defaults
DEFAULT_MAX_STEPS = 20
DEFAULT_TASK_TIMEOUT_S = 300

# Status strings
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
