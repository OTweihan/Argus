# Scripts

工具脚本集合。运维相关脚本只依赖 Python 3.11+ 标准库，可以在没装项目依赖的运维机上直接跑。

## 运维脚本

### `backup_db.py` — 数据库在线热备份

私网部署的生产数据丢失后没人能救回来。本脚本用 SQLite `Connection.backup()` API 在线复制数据库（不需要停服），同时备份 `config/.fernet_key`（缺它则备份出的 model_configs API Key 无法解密）。

用法：

```pwsh
python scripts/backup_db.py                        # 默认输出到 outputs/backups/
python scripts/backup_db.py --dest D:\backups\argus  # 备份到外置盘
python scripts/backup_db.py --keep 7               # 自动只保留最近 7 个
```

建议放进定时任务（cron / Windows 计划任务）每日凌晨运行。

### `cleanup_outputs.py` — 清理过期产物

长期部署后 `outputs/screenshots`、`outputs/temp`、`outputs/logs` 会无限堆积。脚本按文件 mtime 清理超龄文件，与 `config/server.yaml` 的 `llm_trace.retention_days`（启动期清 trace）形成互补。

用法：

```pwsh
python scripts/cleanup_outputs.py                       # 清 30 天前
python scripts/cleanup_outputs.py --days 7
python scripts/cleanup_outputs.py --dry-run             # 预览
python scripts/cleanup_outputs.py --targets logs,temp   # 只清指定子目录
```

`outputs/data`（数据库本体）与 `outputs/backups` 是受保护目录，本脚本拒绝清理。

## 开发脚本

- `dev.mjs` — Windows、macOS、Linux 通用的本地开发进程管理器。要求 Node.js 20+，
  同时启动 uv 管理的 Python API、Vite 前端和 Java Analyzer：

  ```pwsh
  node scripts/dev.mjs --check  # 只检查环境和端口
  node scripts/dev.mjs          # 启动全部服务，Ctrl+C 停止
  ```

  Python 直接使用 uv 创建的 `.venv`：Windows 为 `.venv\Scripts\python.exe`，
  macOS/Linux 为 `.venv/bin/python`。启动器不会自动安装或更新依赖；环境缺失时执行：

  ```pwsh
  uv sync --frozen --extra browser --dev
  pnpm --dir frontend install --frozen-lockfile
  ```

  聚合日志写入 `outputs/logs/dev/<启动时间>/combined.log`，同时保留
  `python.log`、`frontend.log` 和 `java.log`。日志不会自动清理，并可能包含敏感运行信息。

- `codegen.mjs` — 由前端 `pnpm codegen:openapi` 调用，生成 `frontend/src/api/openapi.gen.ts`。
- `export_openapi.py` — 把 FastAPI 运行时 OpenAPI schema 导出到 `frontend/src/api/openapi.json`，被 `codegen.mjs` 调用。
- `pre-commit-*.py` — pre-commit hook 集，按 `.pre-commit-config.yaml` 调度。
