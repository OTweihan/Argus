-- 0006: 关联运行按 analysis_id 查询索引
-- FORWARD-ONLY: SQLite 不支持 DROP COLUMN，此迁移不可回滚
-- 由 schema_migrations 版本机制保证仅执行一次（SQL 本身不保证可重放）

-- correlation_runs.analysis_id 此前没有独立索引：0004 的 uq_correlation_bound
-- 以 blackbox_run_id 打头，无法为 `WHERE analysis_id IN (...)` 所用，
-- list_by_analysis_ids / build_correlation_report_data 因此走全表扫描。
-- 部分索引（analysis_id IS NOT NULL）与 uq_correlation_bound 语义一致，
-- 只覆盖已绑定白盒分析的运行。
CREATE INDEX IF NOT EXISTS idx_correlation_analysis
    ON correlation_runs(analysis_id)
    WHERE analysis_id IS NOT NULL;
