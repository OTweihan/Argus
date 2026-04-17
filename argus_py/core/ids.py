"""Simple ID generation using uuid4 with timestamp prefix."""

import time
import uuid


def generate_id(prefix: str = "arg") -> str:
    """Generate a short unique ID.

    Format: {prefix}-{timestamp_ms_short}-{uuid_short}
    Example: arg-1a2b-c4d5e6f7
    """
    ts = int(time.time() * 1000) & 0xFFFF  # last 16 bits of ms timestamp
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}-{ts:x}-{short_uuid}"


def generate_task_id() -> str:
    """Generate a task-specific ID."""
    return generate_id("task")


def generate_finding_id() -> str:
    """Generate a finding-specific ID."""
    return generate_id("find")
