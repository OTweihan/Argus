"""服务启动时修正中断任务（running → failed）。

语义说明
--------
- **仅处理 SQLite 中 status = "running" 的任务**，将其标记为 failed。
- 不处理 PENDING 任务：崩溃前已入队但尚未被 Worker 消费的任务，其 SQLite
  status 为 PENDING，恢复后不被影响。用户可手动重启这些 PENDING 任务。
- **重启不重排队。** ``TaskQueue`` 的内存集合在重启后丢失，且当前没有
  SQLite 队列持久化表。如需自动恢复入队，需新增 ``task_queue`` 表并在
  本函数中重建队列。

这属于有意设计而非疏漏：对于非持久化队列，崩溃时在途任务的确定性恢复
代价过高，保持 PENDING 可让用户按需决定是否重新提交。
"""

from __future__ import annotations

import logging

from argus_py.core.enums import TaskStatus
from argus_py.task.service import TaskService

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "服务重启导致任务中断，请重新创建或重新启动任务。"


def recover_interrupted_tasks(task_service: TaskService) -> int:
    """将重启前残留的 running 任务标记为 failed。

    不处理 PENDING / QUEUED 任务 —— 它们保留原状态，用户可按需手动重提。

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
