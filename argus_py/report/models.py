"""Report data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from argus_py.core.enums import FindingSeverity, FindingType


@dataclass
class Finding:
    """A discovered issue or observation."""

    title: str
    description: str
    severity: FindingSeverity
    finding_type: FindingType
    url: Optional[str] = None
    screenshot_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class StepLog:
    """A single execution step record."""

    step_number: int
    action: str
    target: Optional[str] = None
    result: str = ""
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
