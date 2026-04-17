"""Task data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from argus_py.core.enums import TaskStatus, TaskType
from argus_py.core.ids import generate_task_id


@dataclass
class Task:
    """Represents a single test task."""

    goal: str
    task_type: TaskType = TaskType.BLACKBOX
    status: TaskStatus = TaskStatus.PENDING
    task_id: str = field(default_factory=generate_task_id)
    start_url: Optional[str] = None
    max_steps: int = 20
    timeout_seconds: int = 300
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
