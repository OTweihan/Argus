"""白盒任务类型化异常 — 由 TaskRunner 捕获并映射为任务终态。"""

from __future__ import annotations


class WhiteboxTaskError(Exception):
    """白盒任务错误基类。TaskRunner 捕获并映射为 FAILED。"""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class WhiteboxSourceResolutionError(WhiteboxTaskError):
    """源码解析失败 → FAILED。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="WHITEBOX_SOURCE_RESOLUTION_ERROR")


class WhiteboxVisibilityError(WhiteboxTaskError):
    """源码可见性校验失败 → FAILED。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="WHITEBOX_VISIBILITY_ERROR")


class WhiteboxTaskCancelled(WhiteboxTaskError):
    """任务被取消 → CANCELLED。

    由 TaskRunner._handle_cancelled() 处理。

    阶段一：只停止 Python 侧轮询，不尝试中断远端分析线程。
    消息必须明确说明远端作业可能仍在运行。
    """

    def __init__(self, job_id: str, origin: str = "local") -> None:
        self.job_id = job_id
        self.origin = origin  # "local" | "remote"

        if origin == "remote":
            msg = f"远端作业已取消, job={job_id}"
        else:
            msg = f"白盒任务已取消（只停止等待，远端作业可能仍在运行）, job={job_id}"
        super().__init__(msg, error_code="WHITEBOX_TASK_CANCELLED")


class WhiteboxTaskTimeout(WhiteboxTaskError):
    """分析超时 → TIMEOUT。

    由 TaskRunner._handle_timeout() 处理。
    """

    def __init__(self, job_id: str, deadline: float) -> None:
        self.job_id = job_id
        self.deadline = deadline
        super().__init__(
            f"白盒分析超时({deadline:.0f}s), job={job_id}",
            error_code="WHITEBOX_TASK_TIMEOUT",
        )


class WhiteboxRemoteJobFailed(WhiteboxTaskError):
    """Java 作业失败 → FAILED。"""

    def __init__(self, job_id: str, error: str | None) -> None:
        self.job_id = job_id
        super().__init__(
            f"Java 远端作业失败: {error or 'unknown'}, job={job_id}",
            error_code="WHITEBOX_REMOTE_JOB_FAILED",
        )
