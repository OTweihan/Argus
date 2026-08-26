"""回归测试闭环领域模型。

设计要点（见 docs/optimizations/regression-test-closed-loop-plan.md）：
- 用例保存**解析后的可执行输入**（保存时经 ``TaskApplicationService.resolve_create_params``
  校验与项目默认值合并），运行批次时直接按快照创建任务，保证可重放；
- 批次项持有用例配置快照（``case_snapshot_json``），后续用例编辑不影响
  历史批次的可审计性；
- 批次是协调记录，不是任务状态的写入者：子任务的执行状态、步骤、产物和
  报告仍以 tasks 表为唯一事实来源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from argus_py.core.constants import DEFAULT_MAX_STEPS, DEFAULT_TASK_TIMEOUT_S
from argus_py.core.enums import TaskType
from argus_py.regression.enums import (
    RegressionGateResult,
    RegressionItemStatus,
    RegressionRunStatus,
    RegressionTriggerSource,
)


@dataclass
class RegressionCase:
    """回归用例：项目内可重复执行的任务模板。"""

    case_id: str
    project_id: str
    name: str
    task_type: TaskType = TaskType.BLACKBOX
    goal: str = ""
    start_url: str | None = None
    # 以下三个为 resolve 后的具体值（非 None），运行时直接透传给 create_task
    max_steps: int = DEFAULT_MAX_STEPS
    timeout_seconds: int = DEFAULT_TASK_TIMEOUT_S
    capture_screenshots: bool = True
    # 解析合并后的任务 parameters JSON（含 model_config_id / prompt_extensions /
    # 白盒 scope/target_modules/maven 等）
    parameters_json: str = "{}"
    whitebox_config_json: str | None = None
    enabled: bool = True
    display_order: int = 0
    created_at: str = ""
    updated_at: str = ""

    def resolved_parameters(self) -> dict[str, Any]:
        """返回解析后的 parameters dict。"""
        import json

        try:
            data = json.loads(self.parameters_json)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


@dataclass
class RegressionRun:
    """回归批次。

    ``baseline_run_id`` 在创建时固定为本项目当前基线批次（可为 None 表示
    首跑无对比）；差异报告始终相对该基线计算，不受事后基线切换影响。
    """

    run_id: str
    project_id: str
    trigger_source: RegressionTriggerSource = RegressionTriggerSource.API
    triggered_by: str | None = None
    baseline_run_id: str | None = None
    status: RegressionRunStatus = RegressionRunStatus.PENDING
    gate_result: RegressionGateResult | None = None
    # 终态汇总：itemCounts / findingTotals / diff(added/persistent/resolved/truncated)
    # / blockingReasons / fingerprintVersion，结构见 application._build_summary
    summary_json: str = "{}"
    is_baseline: bool = False
    error_code: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = ""


@dataclass
class RegressionRunItem:
    """回归批次项：用例快照与其子任务的关联。"""

    item_id: str
    run_id: str
    case_id: str
    case_name: str = ""
    display_order: int = 0
    # 创建时刻的完整用例配置快照（JSON 序列化的 RegressionCase 可重放字段）
    case_snapshot_json: str = "{}"
    # 子任务 ID；创建后回填。tasks 行被删除时由 FK ON DELETE SET NULL 置空。
    task_id: str | None = None
    status: RegressionItemStatus = RegressionItemStatus.PENDING
    finding_count: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = ""


@dataclass
class CaseSnapshot:
    """从用例/快照 JSON 还原的可执行输入视图（批次提交与差异匹配共用）。"""

    case_id: str
    name: str
    task_type: TaskType
    goal: str
    start_url: str | None
    max_steps: int
    timeout_seconds: int
    capture_screenshots: bool
    parameters: dict[str, Any] = field(default_factory=dict)
    whitebox_config_json: str | None = None

    @classmethod
    def from_case(cls, case: RegressionCase) -> "CaseSnapshot":
        return cls(
            case_id=case.case_id,
            name=case.name,
            task_type=case.task_type,
            goal=case.goal,
            start_url=case.start_url,
            max_steps=case.max_steps,
            timeout_seconds=case.timeout_seconds,
            capture_screenshots=case.capture_screenshots,
            parameters=case.resolved_parameters(),
            whitebox_config_json=case.whitebox_config_json,
        )
