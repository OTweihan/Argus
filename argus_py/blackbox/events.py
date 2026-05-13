"""黑盒 Agent 时间线事件发射器。"""

from __future__ import annotations

from argus_py.task.service import TaskService


class BlackboxEvents:
    """黑盒各阶段统一发射时间线事件。"""

    def __init__(self, service: TaskService) -> None:
        self.service = service

    def task_start(self, task_id: str, goal: str, start_url: str) -> None:
        self.service.emit_timeline(
            task_id,
            "start",
            "task",
            summary="任务启动",
            data={"goal": goal, "startUrl": start_url},
        )

    def action(
        self,
        task_id: str,
        step_number: int,
        action_value: str,
        selector: str | None,
        url: str | None,
    ) -> None:
        self.service.emit_timeline(
            task_id,
            "action",
            "executor",
            step_number=step_number,
            summary=f"执行 {action_value}",
            data={"action": action_value, "selector": selector, "url": url},
        )

    def planner_start(self, task_id: str, step: int, goal: str, current_url: str) -> None:
        self.service.emit_timeline(
            task_id,
            "planner_start",
            "planner",
            step_number=step,
            summary="Planner 开始规划",
            data={"goal": goal, "currentUrl": current_url},
        )

    def planner_result(self, task_id: str, step: int, step_count: int, plan_summary: str) -> None:
        self.service.emit_timeline(
            task_id,
            "planner_result",
            "planner",
            step_number=step,
            summary=f"Planner 输出 {step_count} 个动作",
            data={"stepCount": step_count, "planSummary": plan_summary},
        )

    def evaluator_start(self, task_id: str, step: int, goal: str) -> None:
        self.service.emit_timeline(
            task_id,
            "evaluator_start",
            "evaluator",
            step_number=step,
            summary="Evaluator 开始判断",
            data={"goal": goal},
        )

    def evaluator_result(
        self,
        task_id: str,
        step: int,
        success: bool,
        completed: bool,
        reason: str,
        finding_count: int,
    ) -> None:
        self.service.emit_timeline(
            task_id,
            "evaluator_result",
            "evaluator",
            step_number=step,
            summary="成功" if success else "失败",
            data={
                "completed": completed,
                "success": success,
                "reason": reason,
                "findingCount": finding_count,
            },
        )

    def complete(self, task_id: str) -> None:
        self.service.emit_timeline(task_id, "complete", "task", summary="任务完成")

    def fail(self, task_id: str, message: str) -> None:
        self.service.emit_timeline(
            task_id,
            "fail",
            "task",
            summary="任务异常",
            data={"errorMessage": message},
        )

    def max_steps(self, task_id: str, message: str) -> None:
        self.service.emit_timeline(
            task_id,
            "fail",
            "task",
            summary="达到最大步骤",
            data={"errorMessage": message},
        )
