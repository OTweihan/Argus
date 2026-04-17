"""Test fixtures."""

import pytest


@pytest.fixture
def sample_task_data():
    """Sample task data for testing."""
    return {
        "goal": "Open example.com and verify the page title",
        "url": "https://example.com",
        "max_steps": 5,
        "timeout_s": 30,
    }


@pytest.fixture
def sample_finding():
    """Sample finding for testing."""
    return {
        "title": "Page title mismatch",
        "description": "Expected 'Example Domain' but got 'Not Found'",
        "severity": "high",
        "type": "functional",
    }
