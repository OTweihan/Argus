"""服务启动时修正中断任务（running → failed）。"""

from __future__ import annotations

import logging

from argus_py.core.enums import TaskStatus
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "服务重启导致任务中断，请重新创建或重新启动任务。"


def recover_interrupted_tasks(task_service: TaskService) -> int:
    """将重启前残留的 running 任务标记为 failed。

    返回修正的任务数量。
    """
    running_tasks = task_service.list_tasks(status=TaskStatus.RUNNING)
    if not running_tasks:
        logger.info("没有残留的 running 任务需要恢复。")
        return 0

    count = 0
    for task in running_tasks:
        try:
            task_service.fail_task(task, INTERRUPTED_MESSAGE)
            count += 1
            logger.info("已修正中断任务：%s", task.task_id)
        except Exception:
            logger.exception("恢复中断任务失败：%s", task.task_id)

    logger.info("中断任务恢复完成：%d / %d", count, len(running_tasks))
    return count
