"""临时文件残留清理。

调试包下载（``argus_py/api/routes/events.py::download_debug_bundle``）与
诊断导出/诊断包（``argus_py/observability/diagnostics_export.py``）会在
``tempfile.gettempdir()`` 下创建带固定前缀的 zip，并通过 FastAPI 的
``BackgroundTask(os.unlink, ...)`` 在响应完成后删除。

但下面两类场景仍可能留下残留：

1. 进程在响应未完整返回前被强制 kill（OOM Killer / Ctrl+C / 部署滚动）。
2. ``os.unlink`` 因权限或文件锁失败（Windows 下尤其明显）。

该模块提供 ``cleanup_stale_debug_bundles()``，在 FastAPI lifespan 启动阶段
扫描临时目录，删除超过最小寿命的同前缀残留。函数对任何 OS 错误保持静默
（仅 logger.warning），保证启动流程不会被脏文件阻断。

前缀常量由本模块定义，events / diagnostics_export 反向 import，确保
``infra`` 层不依赖 ``api`` / ``observability`` 层（保持单向依赖）。
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

#: 任务调试包临时文件名前缀。
DEBUG_BUNDLE_TMP_PREFIX = "argus-debug-"

#: 诊断中心导出 / 诊断包临时文件名前缀。
DIAGNOSTICS_BUNDLE_TMP_PREFIX = "argus-diag-"

#: 启动期默认一并清理的前缀集合。
_DEFAULT_CLEANUP_PREFIXES = (DEBUG_BUNDLE_TMP_PREFIX, DIAGNOSTICS_BUNDLE_TMP_PREFIX)

logger = logging.getLogger(__name__)

# 残留文件最少需要存在多久才会被清理（秒）。设置 60s 阈值以避免误删
# 当前正在被另一个 worker 写入的 zip。
_MIN_AGE_SECONDS = 60


def cleanup_stale_temp_zips(
    tmp_dir: Path | None = None,
    *,
    prefixes: tuple[str, ...] | list[str] = _DEFAULT_CLEANUP_PREFIXES,
    min_age_seconds: int = _MIN_AGE_SECONDS,
) -> int:
    """清理临时目录下名为 ``{prefix}*.zip`` 且超过 ``min_age_seconds`` 的残留文件。

    返回成功删除的文件数量。任何错误均被吞掉并以 warning 形式记录，使本函数
    可以放心地放在 FastAPI lifespan 启动钩子里。

    Args:
        tmp_dir: 临时目录路径，默认 ``tempfile.gettempdir()``。
        prefixes: 文件名前缀列表（任务调试包 + 诊断导出包）。
        min_age_seconds: 文件最短存活时间（秒）；过短可能误删正在写入的文件。
    """
    target_dir = Path(tmp_dir) if tmp_dir is not None else Path(tempfile.gettempdir())
    if not target_dir.is_dir():
        return 0

    prefix_tuple = tuple(p for p in prefixes if p)
    if not prefix_tuple:
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
            if not name.endswith(".zip"):
                continue
            if not any(name.startswith(prefix) for prefix in prefix_tuple):
                continue
            if not entry.is_file():
                continue
            if entry.stat().st_mtime > cutoff:
                continue
            entry.unlink()
            removed += 1
        except OSError as exc:
            # Windows 下文件被占用 / 权限问题；不致命，跳过即可。
            logger.warning("清理临时 zip 残留失败 %s: %s", entry, exc)
            continue

    if removed:
        logger.info("启动期清理临时 zip 残留 %d 个 (dir=%s)", removed, target_dir)
    return removed


def cleanup_stale_debug_bundles(
    tmp_dir: Path | None = None,
    *,
    prefix: str | None = None,
    min_age_seconds: int = _MIN_AGE_SECONDS,
) -> int:
    """兼容入口：清理调试包与诊断导出包残留。

    ``prefix`` 若显式传入则只清该前缀；默认清调试包 + 诊断包两类前缀。
    """
    if prefix is not None:
        return cleanup_stale_temp_zips(tmp_dir, prefixes=(prefix,), min_age_seconds=min_age_seconds)
    return cleanup_stale_temp_zips(tmp_dir, min_age_seconds=min_age_seconds)


__all__ = [
    "DEBUG_BUNDLE_TMP_PREFIX",
    "DIAGNOSTICS_BUNDLE_TMP_PREFIX",
    "cleanup_stale_debug_bundles",
    "cleanup_stale_temp_zips",
]
