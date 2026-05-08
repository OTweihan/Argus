"""应用异常层级。"""


class ArgusError(Exception):
    """Argus 基础异常。"""


class ConfigError(ArgusError):
    """配置缺失或无效。"""


class LLMError(ArgusError):
    """LLM 调用失败。"""


class LLMRateLimitError(LLMError):
    """LLM 供应商限流。"""


class BrowserError(ArgusError):
    """浏览器操作失败。"""


class TaskError(ArgusError):
    """任务执行失败，支持结构化错误码。"""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class ProjectError(ArgusError):
    """项目管理失败。"""


class ModelConfigError(ConfigError):
    """模型配置管理失败。"""


class ReportError(ArgusError):
    """报告生成失败。"""
