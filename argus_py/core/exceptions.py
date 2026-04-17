"""Application exception hierarchy."""


class ArgusError(Exception):
    """Base exception for Argus."""

    pass


class LLMError(ArgusError):
    """LLM API call failure."""

    pass


class LLMRateLimitError(LLMError):
    """Rate limited by LLM provider."""

    pass


class BrowserError(ArgusError):
    """Browser operation failure."""

    pass


class ElementNotFoundError(BrowserError):
    """Target element not found on page."""

    pass


class TaskError(ArgusError):
    """Task execution failure."""

    pass


class ConfigError(ArgusError):
    """Missing or invalid configuration."""

    pass
