-- 0005: 重试链 — 记录直接父任务，部分唯一索引约束一个任务最多一个直接重试子任务
-- FORWARD-ONLY: SQLite 不支持 DROP COLUMN，此迁移不可回滚
-- 由 schema_migrations 版本机制保证仅执行一次（SQL 本身不保证可重放）

ALTER TABLE tasks ADD COLUMN retry_parent_task_id TEXT;

-- 部分唯一索引：允许任意多个 NULL（普通任务不受影响），非空值全局唯一，
-- 从数据库层兜底"一个任务最多只能有一个直接重试子任务"的线性重试链不变量。
-- 该索引同时供 has_retry_child 查询，不另建普通索引。
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_retry_parent
    ON tasks(retry_parent_task_id)
    WHERE retry_parent_task_id IS NOT NULL;
