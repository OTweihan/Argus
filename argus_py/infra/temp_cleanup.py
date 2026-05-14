"""临时文件残留清理。

调试包下载（``argus_py/api/routes/events.py::download_debug_bundle``）会在
``tempfile.gettempdir()`` 下创建带 ``argus-debug-`` 前缀的 zip，并通过
FastAPI 的 ``BackgroundTask(os.unlink, ...)`` 在响应完成后删除。

但下面两类场景仍可能留下残留：

1. 进程在响应未完整返回前被强制 kill（OOM Killer / Ctrl+C / 部署滚动）。
2. ``os.unlink`` 因权限或文件锁失败（Windows 下尤其明显）。

该模块提供 ``cleanup_stale_debug_bundles()``，在 FastAPI lifespan 启动阶段
扫描临时目录，删除超过最小寿命的同前缀残留。函数对任何 OS 错误保持静默
（仅 logger.warning），保证启动流程不会被脏文件阻断。

这里同时定义 ``DEBUG_BUNDLE_TMP_PREFIX`` 常量；events 路由反向 import 该
常量，确保 ``infra`` 层不依赖 ``api`` 层（保持单向依赖）。
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

#: 调试包临时文件名前缀；events 路由创建文件时使用，本模块按它扫描残留。
DEBUG_BUNDLE_TMP_PREFIX = "argus-debug-"

logger = logging.getLogger(__name__)

# 残留文件最少需要存在多久才会被清理（秒）。设置 60s 阈值以避免误删
# 当前正在被另一个 worker 写入的 zip。
_MIN_AGE_SECONDS = 60


def cleanup_stale_debug_bundles(
    tmp_dir: Path | None = None,
    *,
    prefix: str = DEBUG_BUNDLE_TMP_PREFIX,
    min_age_seconds: int = _MIN_AGE_SECONDS,
) -> int:
    """清理临时目录下名为 ``{prefix}*.zip`` 且超过 ``min_age_seconds`` 的残留文件。

    返回成功删除的文件数量。任何错误均被吞掉并以 warning 形式记录，使本函数
    可以放心地放在 FastAPI lifespan 启动钩子里。

    Args:
        tmp_dir: 临时目录路径，默认 ``tempfile.gettempdir()``。
        prefix: 文件名前缀，默认与 ``download_debug_bundle`` 中保持一致。
        min_age_seconds: 文件最短存活时间（秒）；过短可能误删正在写入的文件。
    """
    target_dir = Path(tmp_dir) if tmp_dir is not None else Path(tempfile.gettempdir())
    if not target_dir.is_dir():
        return 0

    cutoff = time.time() - max(0, min_age_seconds)
    removed = 0
    try:
        candidates = list(target_dir.iterdir())
    except OSError as exc:
        logger.warning("扫描临时目录失败 %s: %s", target_dir, exc)
        return 0

    for entry in candidates:
        try:
            name = entry.name
            if not name.startswith(prefix) or not name.endswith(".zip"):
                continue
            if not entry.is_file():
                continue
            if entry.stat().st_mtime > cutoff:
                continue
            entry.unlink()
            removed += 1
        except OSError as exc:
            # Windows 下文件被占用 / 权限问题；不致命，跳过即可。
            logger.warning("清理调试包残留失败 %s: %s", entry, exc)
            continue

    if removed:
        logger.info("启动期清理调试包残留 %d 个 (dir=%s)", removed, target_dir)
    return removed


__all__ = ["DEBUG_BUNDLE_TMP_PREFIX", "cleanup_stale_debug_bundles"]
