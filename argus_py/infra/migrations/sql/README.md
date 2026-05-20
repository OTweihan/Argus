# SQLite 增量迁移目录

启动期 `apply_migrations()` 会按版本号顺序应用本目录下的 `.sql` 文件。

## 命名规则

```
{version:04d}_{description}.sql
```

例：

- `0001_add_task_priority.sql`
- `0002_create_audit_log_table.sql`

约束：

- `version` 从 `0001` 起；`0000` 被保留作为 baseline（现有 `init_database()`
  建的 schema 全集）。
- 版本号必须连续递增、不可重用（一旦发布到生产环境，禁止改名或重写）。
- 描述部分用 snake_case，简明体现 schema 改动意图。

## 编写规范

- 文件必须是幂等 SQL：若失败需重跑，要能从中断处再来一次（用 `IF NOT EXISTS`
  / `IF EXISTS`）。
- 不允许把 `DROP TABLE`、`DELETE FROM` 等不可逆破坏操作写在迁移里，必须先
  在 changelog 标注并经过人评审。
- 单文件原子：runner 在独立事务中执行整个文件；写入失败会回滚。
- 避免在迁移文件里硬编码业务数据；如需要数据补齐，单独写 Python 脚本。

## 与历史 ALTER 兼容

[argus_py/infra/db.py](../db.py) 中的 `_migrate_tasks_table` 与
`_migrate_model_configs_table` 是历史用户兜底的就地 ALTER；新增 schema 改动
请走本目录的迁移文件而非继续扩展这两个函数。
