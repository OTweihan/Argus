"""白盒任务类型化异常 — 由 TaskRunner 捕获并映射为任务终态。"""

from __future__ import annotations


class WhiteboxTaskError(Exception):
    """白盒任务错误基类。TaskRunner 捕获并映射为 FAILED。"""


class WhiteboxSourceResolutionError(WhiteboxTaskError):
    """源码解析失败 → FAILED。"""


class WhiteboxVisibilityError(WhiteboxTaskError):
    """源码可见性校验失败 → FAILED。"""


class WhiteboxTaskCancelled(WhiteboxTaskError):
    """任务被取消 → CANCELLED。

    由 TaskRunner._handle_cancelled() 处理。
    """

    def __init__(self, job_id: str, origin: str = "local") -> None:
        self.job_id = job_id
        self.origin = origin  # "local" | "remote"
        super().__init__(f"白盒任务已取消 (origin={origin}), job={job_id}")


class WhiteboxTaskTimeout(WhiteboxTaskError):
    """分析超时 → TIMEOUT。

    由 TaskRunner._handle_timeout() 处理。
    """

    def __init__(self, job_id: str, deadline: float) -> None:
        self.job_id = job_id
        self.deadline = deadline
        super().__init__(f"白盒分析超时({deadline:.0f}s), job={job_id}")


class WhiteboxRemoteJobFailed(WhiteboxTaskError):
    """Java 作业失败 → FAILED。"""

    def __init__(self, job_id: str, error: str | None) -> None:
        self.job_id = job_id
        super().__init__(f"Java 远端作业失败: {error or 'unknown'}, job={job_id}")
