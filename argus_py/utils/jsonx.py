"""File system utilities."""

import json
from pathlib import Path
from typing import Any


def write_json(path: str, data: Any, indent: int = 2) -> None:
    """Write data to a JSON file.

    Args:
        path: File path.
        data: JSON-serializable data.
        indent: JSON indentation.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def read_json(path: str) -> Any:
    """Read data from a JSON file.

    Args:
        path: File path.

    Returns:
        Parsed JSON data.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
