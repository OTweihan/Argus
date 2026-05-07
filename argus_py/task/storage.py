"""任务文件存储。"""

from __future__ import annotations

from pathlib import Path

from argus_py.core.paths import TEMP_DIR
from argus_py.task.models import Task
from argus_py.utils.jsonx import read_json, to_jsonable, write_json


class TaskFileStorage:
    """基于文件系统的任务存储，供 MVP 阶段替代数据库。"""

    def __init__(self, base_dir: str | Path = TEMP_DIR / "tasks") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def task_path(self, task_id: str) -> Path:
        """返回任务 JSON 路径。"""
        return self.base_dir / f"{task_id}.json"

    def exists(self, task_id: str) -> bool:
        """判断任务快照是否存在。"""
        return self.task_path(task_id).exists()

    def save(self, task: Task) -> Path:
        """保存任务快照。"""
        return write_json(self.task_path(task.task_id), to_jsonable(task))

    def load_raw(self, task_id: str) -> dict:
        """读取任务原始 JSON 数据。"""
        return read_json(self.task_path(task_id))

    def load(self, task_id: str) -> Task:
        """读取并还原任务实体。"""
        return Task.from_dict(self.load_raw(task_id))

    def list_ids(self) -> list[str]:
        """列出已保存任务 ID（按文件名字母序，即大致按创建时间排序）。"""
        return sorted(path.stem for path in self.base_dir.glob("*.json"))

    def list_tasks(self, offset: int = 0, limit: int | None = None) -> list[Task]:
        """列出已保存任务，支持分页以减轻磁盘 I/O。"""
        ids = self.list_ids()
        ids.reverse()
        if offset:
            ids = ids[offset:]
        if limit is not None:
            ids = ids[:limit]
        tasks = [self.load(task_id) for task_id in ids]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def count_tasks(self) -> int:
        """快速返回任务总数（仅列文件名，不反序列化）。"""
        return len(self.list_ids())
