-- Argus 阶段二：白盒结果结构化持久化
-- 分析执行记录 + 6 张结构化投影表 + findings 表补列
--
-- 幂等性由 migration history 表（schema_migrations）保证：
-- 本文件仅在 migration engine 确认 version=2 未执行时运行一次，
-- 单条 SQL 不要求可重复执行（ALTER TABLE ADD COLUMN 不可重复）。
-- 与 0001_whitebox_productization.sql 约定一致。

-- ============================================================
-- 分析执行记录
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    source_snapshot_id TEXT NOT NULL,
    resolved_commit_sha TEXT,
    run_status TEXT NOT NULL DEFAULT 'QUEUED',
    completeness_status TEXT NOT NULL DEFAULT 'NOT_EVALUATED',
    external_job_id TEXT,
    external_job_status TEXT,
    failure_code TEXT,
    failure_message TEXT,
    stop_reason TEXT,
    result_schema_version INTEGER NOT NULL,
    result_digest TEXT,
    config_json TEXT NOT NULL,
    raw_result_json TEXT,
    quality_policy_version INTEGER NOT NULL DEFAULT 1,
    quality_issues_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT,
    completed_at TEXT,
    projection_completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_task
    ON analysis_runs(task_id, created_at DESC);

-- ============================================================
-- 端点（阶段三精确/模板/仅路径三级匹配）
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_endpoints (
    endpoint_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    endpoint_fingerprint TEXT NOT NULL,
    http_method TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    normalized_exact_path TEXT,
    normalized_path_template TEXT NOT NULL,
    is_templated INTEGER NOT NULL DEFAULT 0,
    path_normalization_version INTEGER NOT NULL DEFAULT 1,
    path_segment_count INTEGER NOT NULL DEFAULT 0,
    static_prefix TEXT,
    canonical_path_shape TEXT,
    controller_class TEXT,
    controller_method TEXT,
    controller_method_signature TEXT,
    parameters TEXT,
    return_type TEXT,
    source_file TEXT,
    source_start_line INTEGER,
    source_start_column INTEGER,
    source_end_line INTEGER,
    source_end_column INTEGER,
    entry_call_node_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_endpoints_fingerprint
    ON analysis_endpoints(analysis_id, endpoint_fingerprint);

CREATE INDEX IF NOT EXISTS idx_endpoints_exact_match
    ON analysis_endpoints(analysis_id, http_method, normalized_exact_path)
    WHERE normalized_exact_path IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_endpoint_template_candidates
    ON analysis_endpoints(analysis_id, http_method, path_segment_count, static_prefix);

CREATE INDEX IF NOT EXISTS idx_endpoints_path_only
    ON analysis_endpoints(analysis_id, normalized_path_template);

-- ============================================================
-- 调用图节点
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_call_nodes (
    call_node_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    call_node_fingerprint TEXT NOT NULL,
    class_name TEXT NOT NULL,
    method_name TEXT NOT NULL,
    method_signature TEXT,
    source_file TEXT,
    source_start_line INTEGER,
    source_start_column INTEGER,
    source_end_line INTEGER,
    source_end_column INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_call_nodes_fingerprint
    ON analysis_call_nodes(analysis_id, call_node_fingerprint);

CREATE UNIQUE INDEX IF NOT EXISTS uq_call_nodes_analysis_id
    ON analysis_call_nodes(analysis_id, call_node_id);

CREATE INDEX IF NOT EXISTS idx_call_nodes_analysis
    ON analysis_call_nodes(analysis_id);

-- ============================================================
-- 调用图边
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_call_edges (
    call_edge_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    to_class_name TEXT,
    to_method_name TEXT,
    resolution_type TEXT,
    confidence TEXT,
    source_file TEXT,
    source_start_line INTEGER,
    source_start_column INTEGER,
    source_end_line INTEGER,
    source_end_column INTEGER
);

CREATE INDEX IF NOT EXISTS idx_call_edges_analysis
    ON analysis_call_edges(analysis_id);
CREATE INDEX IF NOT EXISTS idx_call_edges_from
    ON analysis_call_edges(from_node_id);

-- ============================================================
-- 执行流
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_execution_flows (
    execution_flow_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    execution_flow_fingerprint TEXT NOT NULL DEFAULT '',
    entry_point TEXT NOT NULL,
    call_depth INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_flows_fingerprint
    ON analysis_execution_flows(analysis_id, execution_flow_fingerprint);

CREATE INDEX IF NOT EXISTS idx_flows_analysis
    ON analysis_execution_flows(analysis_id);

CREATE TABLE IF NOT EXISTS analysis_flow_steps (
    flow_step_id TEXT PRIMARY KEY,
    execution_flow_id TEXT NOT NULL REFERENCES analysis_execution_flows(execution_flow_id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    method_key TEXT NOT NULL,
    class_name TEXT,
    method_name TEXT,
    call_node_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_steps
    ON analysis_flow_steps(execution_flow_id, step_index);

CREATE INDEX IF NOT EXISTS idx_flow_steps_flow
    ON analysis_flow_steps(execution_flow_id, step_index);

-- ============================================================
-- 诊断信息
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_diagnostics (
    analysis_id TEXT PRIMARY KEY REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    total_source_files INTEGER NOT NULL DEFAULT 0,
    eligible_source_files INTEGER NOT NULL DEFAULT 0,
    parsed_file_count INTEGER NOT NULL DEFAULT 0,
    failed_file_count INTEGER NOT NULL DEFAULT 0,
    failed_files TEXT,
    total_calls INTEGER NOT NULL DEFAULT 0,
    resolved_high INTEGER NOT NULL DEFAULT 0,
    resolved_medium INTEGER NOT NULL DEFAULT 0,
    resolved_low INTEGER NOT NULL DEFAULT 0,
    unresolved INTEGER NOT NULL DEFAULT 0,
    classpath_available INTEGER NOT NULL DEFAULT 0,
    jar_count INTEGER NOT NULL DEFAULT 0,
    classpath_source TEXT,
    classpath_warnings TEXT,
    classpath_errors TEXT,
    module_count INTEGER NOT NULL DEFAULT 0,
    application_module_count INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- findings 表补列
-- ============================================================
ALTER TABLE findings ADD COLUMN analysis_id TEXT REFERENCES analysis_runs(analysis_id);
ALTER TABLE findings ADD COLUMN snippet TEXT;

CREATE INDEX IF NOT EXISTS idx_findings_analysis ON findings(analysis_id);
CREATE INDEX IF NOT EXISTS idx_findings_analysis_severity ON findings(analysis_id, severity);
CREATE INDEX IF NOT EXISTS idx_findings_analysis_category ON findings(analysis_id, rule_category);
