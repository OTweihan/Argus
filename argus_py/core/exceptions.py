"""应用异常层级。"""


class ArgusError(Exception):
    """Argus 基础异常。"""


class ConfigError(ArgusError):
    """配置缺失或无效。"""


class LLMError(ArgusError):
    """LLM 调用失败（非可重试 —— 响应格式异常等）。"""


class LLMTransientError(LLMError):
    """LLM 临时故障（网络超时、5xx 等），可重试。"""


class LLMRateLimitError(LLMTransientError):
    """LLM 供应商限流。"""


class BrowserError(ArgusError):
    """浏览器操作失败。"""


class TaskError(ArgusError):
    """任务执行失败，支持结构化错误码。"""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class TaskNotFoundError(TaskError):
    """任务实体不存在。

    作为 ``TaskError`` 的精确子类替代 ``"not found" in message`` 的字符串
    匹配，从根本上避免错误消息本地化或重写时丢失 404 语义。
    """


class ProjectError(ArgusError):
    """项目管理失败。"""


class ProjectNotFoundError(ProjectError):
    """项目实体不存在。"""


class ModelConfigError(ConfigError):
    """模型配置管理失败。"""


class ModelConfigNotFoundError(ModelConfigError):
    """模型配置实体不存在。"""


class ReportError(ArgusError):
    """报告生成失败。"""
