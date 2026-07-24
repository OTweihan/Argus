-- 0001: 白盒产品化 — 配置独立持久化、源码快照、外部作业、Finding 语义、结果分离、Worker 租约
-- FORWARD-ONLY: SQLite 不支持 DROP COLUMN，此迁移不可回滚

-- 1. tasks: 白盒配置独立持久化
ALTER TABLE tasks ADD COLUMN whitebox_config_json TEXT;
ALTER TABLE tasks ADD COLUMN whitebox_config_schema_version INTEGER NOT NULL DEFAULT 1;

-- 2. tasks: 结果分离（不再写入 parameters_json）
ALTER TABLE tasks ADD COLUMN result_json TEXT;
ALTER TABLE tasks ADD COLUMN result_schema_version INTEGER;
ALTER TABLE tasks ADD COLUMN result_size_bytes INTEGER;

-- 3. tasks: 源码快照
ALTER TABLE tasks ADD COLUMN source_type TEXT;
ALTER TABLE tasks ADD COLUMN source_repo_url TEXT;
ALTER TABLE tasks ADD COLUMN source_requested_ref TEXT;
ALTER TABLE tasks ADD COLUMN source_resolved_commit_sha TEXT;
ALTER TABLE tasks ADD COLUMN source_ref_type TEXT;
ALTER TABLE tasks ADD COLUMN source_dirty INTEGER;

-- 4. tasks: 远端作业信息
ALTER TABLE tasks ADD COLUMN external_job_id TEXT;
ALTER TABLE tasks ADD COLUMN external_job_status TEXT;
ALTER TABLE tasks ADD COLUMN external_job_submitted_at TEXT;
ALTER TABLE tasks ADD COLUMN external_job_last_polled_at TEXT;

-- 5. tasks: Worker 租约（reconciliation 安全）
ALTER TABLE tasks ADD COLUMN worker_id TEXT;
ALTER TABLE tasks ADD COLUMN worker_lease_expires_at TEXT;

-- 6. tasks: 执行尝试（幂等键 clientRequestId 的组成部分）
ALTER TABLE tasks ADD COLUMN execution_attempt INTEGER NOT NULL DEFAULT 1;

-- 7. findings: 白盒语义字段 + 稳定指纹
ALTER TABLE findings ADD COLUMN rule_id TEXT;
ALTER TABLE findings ADD COLUMN rule_category TEXT;
ALTER TABLE findings ADD COLUMN confidence TEXT;
ALTER TABLE findings ADD COLUMN fingerprint TEXT;

CREATE INDEX IF NOT EXISTS idx_findings_fingerprint ON findings(fingerprint);
