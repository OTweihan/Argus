-- 0004: 黑白盒关联 — 请求证据 + 端点证据 + 关联运行
-- FORWARD-ONLY: SQLite 不支持 DROP COLUMN，此迁移不可回滚

-- ============================================================
-- blackbox_runs: 黑盒执行实例
-- ============================================================
CREATE TABLE IF NOT EXISTS blackbox_runs (
    blackbox_run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED','TIMED_OUT')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (task_id, attempt)
);

-- ============================================================
-- correlation_runs: 黑白盒关联运行
-- ============================================================
CREATE TABLE IF NOT EXISTS correlation_runs (
    correlation_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    blackbox_run_id TEXT NOT NULL REFERENCES blackbox_runs(blackbox_run_id) ON DELETE CASCADE,
    desired_source_snapshot_id TEXT NOT NULL,
    desired_analysis_config_digest TEXT NOT NULL DEFAULT '',
    required_analyzer_version TEXT NOT NULL DEFAULT '',
    allow_partial_analysis INTEGER NOT NULL DEFAULT 0,
    analysis_id TEXT,
    bound_source_snapshot_id TEXT,
    analysis_projection_version INTEGER,
    correlation_config_digest TEXT NOT NULL DEFAULT '',
    matcher_version TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    supersedes_correlation_run_id TEXT,
    source_alignment_status TEXT NOT NULL DEFAULT 'UNVERIFIED'
        CHECK (source_alignment_status IN ('VERIFIED','USER_DECLARED','UNVERIFIED','MISMATCHED')),
    status TEXT NOT NULL DEFAULT 'WAITING_ANALYSIS'
        CHECK (status IN ('WAITING_ANALYSIS','WAITING_BINDING','WAITING_BLACKBOX',
                          'BLOCKED','READY','RUNNING','SUCCEEDED','PARTIAL','FAILED','STALE')),
    active_attempt_id TEXT,
    source_mismatch_overridden INTEGER NOT NULL DEFAULT 0
        CHECK (source_mismatch_overridden IN (0, 1)),
    source_mismatch_override_by TEXT,
    source_mismatch_override_at TEXT,
    source_mismatch_override_reason TEXT,
    started_at TEXT,
    completed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

-- 已绑定阶段唯一索引（analysis_id IS NOT NULL 时）
CREATE UNIQUE INDEX IF NOT EXISTS uq_correlation_bound
    ON correlation_runs(blackbox_run_id, analysis_id, analysis_projection_version,
                        matcher_version, normalization_version, correlation_config_digest)
    WHERE analysis_id IS NOT NULL;

-- 等待阶段唯一索引（analysis_id IS NULL 时）
CREATE UNIQUE INDEX IF NOT EXISTS uq_correlation_waiting
    ON correlation_runs(blackbox_run_id, desired_source_snapshot_id,
                        desired_analysis_config_digest, required_analyzer_version,
                        allow_partial_analysis,
                        matcher_version, normalization_version, correlation_config_digest)
    WHERE analysis_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_correlation_blackbox ON correlation_runs(blackbox_run_id);
CREATE INDEX IF NOT EXISTS idx_correlation_project ON correlation_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_correlation_status ON correlation_runs(status);

-- 组合唯一索引：active_attempt_id 必须属于当前 Run
CREATE UNIQUE INDEX IF NOT EXISTS uq_correlation_run_active_attempt
    ON correlation_runs(correlation_run_id, active_attempt_id)
    WHERE active_attempt_id IS NOT NULL;

-- ============================================================
-- correlation_attempts: 关联尝试
-- ============================================================
CREATE TABLE IF NOT EXISTS correlation_attempts (
    correlation_attempt_id TEXT PRIMARY KEY,
    correlation_run_id TEXT NOT NULL REFERENCES correlation_runs(correlation_run_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,

    -- 冻结的白盒输入（不可变）
    analysis_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    analysis_projection_version INTEGER NOT NULL,
    matcher_version TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    correlation_config_digest TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED','ABORTED')),
    evidence_completeness TEXT NOT NULL DEFAULT 'COMPLETE'
        CHECK (evidence_completeness IN ('COMPLETE','PARTIAL')),

    -- 租约
    lease_owner TEXT,
    heartbeat_at TEXT,
    lease_expires_at TEXT,

    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (correlation_run_id, attempt_number),
    UNIQUE (correlation_run_id, correlation_attempt_id)
);

-- ============================================================
-- http_request_evidence: 黑盒 HTTP 请求证据（已脱敏）
-- ============================================================
CREATE TABLE IF NOT EXISTS http_request_evidence (
    request_evidence_id TEXT PRIMARY KEY,
    blackbox_run_id TEXT NOT NULL REFERENCES blackbox_runs(blackbox_run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    step_execution_id TEXT,
    step_attempt INTEGER NOT NULL DEFAULT 1,
    request_sequence INTEGER NOT NULL,
    http_method TEXT NOT NULL CHECK (http_method = UPPER(http_method)),
    normalized_path TEXT NOT NULL,
    display_path TEXT NOT NULL,
    origin TEXT NOT NULL,
    resource_type TEXT NOT NULL DEFAULT 'other',
    endpoint_match_eligibility TEXT NOT NULL DEFAULT 'CONFIRMED_ELIGIBLE'
        CHECK (endpoint_match_eligibility IN ('CONFIRMED_ELIGIBLE','ATTEMPT_ONLY','EXCLUDED_SW_CACHE')),
    response_status INTEGER,
    outcome TEXT NOT NULL DEFAULT 'COMPLETED'
        CHECK (outcome IN ('COMPLETED','NETWORK_FAILED','ABANDONED')),
    failure_code TEXT,
    request_owner TEXT NOT NULL DEFAULT 'FRAME'
        CHECK (request_owner IN ('FRAME','SERVICE_WORKER')),
    response_from_service_worker INTEGER NOT NULL DEFAULT 0
        CHECK (response_from_service_worker IN (0, 1)),
    page_sequence INTEGER NOT NULL DEFAULT 0,
    captured_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_request_evidence_seq
    ON http_request_evidence(blackbox_run_id, request_sequence);
CREATE INDEX IF NOT EXISTS idx_request_evidence_run_step
    ON http_request_evidence(blackbox_run_id, step_execution_id);
CREATE INDEX IF NOT EXISTS idx_request_evidence_task
    ON http_request_evidence(task_id);

-- ============================================================
-- http_capture_quality: 采集质量统计
-- ============================================================
CREATE TABLE IF NOT EXISTS http_capture_quality (
    blackbox_run_id TEXT PRIMARY KEY REFERENCES blackbox_runs(blackbox_run_id) ON DELETE CASCADE,
    total_observed INTEGER NOT NULL DEFAULT 0,
    accepted_started INTEGER NOT NULL DEFAULT 0,
    persisted_count INTEGER NOT NULL DEFAULT 0,
    filtered_by_resource_type INTEGER NOT NULL DEFAULT 0,
    filtered_cross_origin INTEGER NOT NULL DEFAULT 0,
    filtered_by_method INTEGER NOT NULL DEFAULT 0,
    filtered_websocket_count INTEGER NOT NULL DEFAULT 0,
    filtered_path_too_long INTEGER NOT NULL DEFAULT 0,
    dropped_pending_limit INTEGER NOT NULL DEFAULT 0,
    dropped_run_limit INTEGER NOT NULL DEFAULT 0,
    dropped_writer_queue_limit INTEGER NOT NULL DEFAULT 0,
    writer_retry_count INTEGER NOT NULL DEFAULT 0,
    writer_failed_batch_count INTEGER NOT NULL DEFAULT 0,
    persistence_failed INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    truncation_reason TEXT,
    updated_at TEXT NOT NULL
);

-- ============================================================
-- endpoint_evidence: 端点匹配证据（含组合 FK）
-- ============================================================
CREATE TABLE IF NOT EXISTS endpoint_evidence (
    endpoint_evidence_id TEXT PRIMARY KEY,
    correlation_run_id TEXT NOT NULL,
    correlation_attempt_id TEXT NOT NULL,
    request_evidence_id TEXT NOT NULL REFERENCES http_request_evidence(request_evidence_id) ON DELETE CASCADE,
    resolution_status TEXT NOT NULL
        CHECK (resolution_status IN ('UNIQUE','AMBIGUOUS','UNMATCHED')),
    match_strategy TEXT NOT NULL
        CHECK (match_strategy IN ('EXACT','TEMPLATE','PATH_ONLY','NONE')),
    confidence TEXT NOT NULL
        CHECK (confidence IN ('HIGH','MEDIUM','LOW','UNKNOWN')),
    matched_endpoint_id TEXT,
    match_reason_code TEXT NOT NULL DEFAULT '',
    matcher_version TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (correlation_run_id, correlation_attempt_id)
        REFERENCES correlation_attempts(correlation_run_id, correlation_attempt_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_endpoint_evidence
    ON endpoint_evidence(correlation_attempt_id, request_evidence_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ee_attempt_evidence
    ON endpoint_evidence(correlation_attempt_id, endpoint_evidence_id);
CREATE INDEX IF NOT EXISTS idx_ee_attempt_status
    ON endpoint_evidence(correlation_attempt_id, resolution_status, match_strategy);
CREATE INDEX IF NOT EXISTS idx_ee_attempt_endpoint
    ON endpoint_evidence(correlation_attempt_id, matched_endpoint_id)
    WHERE matched_endpoint_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ee_correlation
    ON endpoint_evidence(correlation_run_id);

-- ============================================================
-- endpoint_evidence_candidates: 候选端点
-- ============================================================
CREATE TABLE IF NOT EXISTS endpoint_evidence_candidates (
    endpoint_evidence_id TEXT NOT NULL REFERENCES endpoint_evidence(endpoint_evidence_id) ON DELETE CASCADE,
    endpoint_id TEXT NOT NULL,
    candidate_rank INTEGER NOT NULL CHECK (candidate_rank >= 1),
    match_strategy TEXT NOT NULL CHECK (match_strategy IN ('EXACT','TEMPLATE','PATH_ONLY','NONE')),
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH','MEDIUM','LOW','UNKNOWN')),
    reason_code TEXT NOT NULL DEFAULT '',
    selected INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0, 1)),
    PRIMARY KEY (endpoint_evidence_id, endpoint_id),
    UNIQUE (endpoint_evidence_id, candidate_rank)
);

-- ============================================================
-- endpoint_evidence_flows: 调用流关联（无 ON DELETE CASCADE 到白盒表）
-- ============================================================
CREATE TABLE IF NOT EXISTS endpoint_evidence_flows (
    endpoint_evidence_id TEXT NOT NULL REFERENCES endpoint_evidence(endpoint_evidence_id) ON DELETE CASCADE,
    execution_flow_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'STATIC_REACHABLE',
    endpoint_method_snapshot TEXT,
    endpoint_path_snapshot TEXT,
    controller_snapshot TEXT,
    flow_name_snapshot TEXT,
    source_location_snapshot TEXT,
    PRIMARY KEY (endpoint_evidence_id, execution_flow_id)
);

-- ============================================================
-- finding_evidence: Finding 关联聚合
-- ============================================================
CREATE TABLE IF NOT EXISTS finding_evidence (
    finding_evidence_id TEXT PRIMARY KEY,
    correlation_attempt_id TEXT NOT NULL REFERENCES correlation_attempts(correlation_attempt_id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    best_relation_type TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (best_relation_type IN ('DIRECT_HANDLER','STATIC_REACHABLE','FLOW_MEMBER','UNKNOWN')),
    minimum_call_distance INTEGER,
    confirmed_request_count INTEGER NOT NULL DEFAULT 0,
    candidate_request_count INTEGER NOT NULL DEFAULT 0,
    finding_rule_id_snapshot TEXT,
    finding_location_snapshot TEXT,
    UNIQUE (correlation_attempt_id, finding_id)
);

CREATE INDEX IF NOT EXISTS idx_fe_correlation_attempt ON finding_evidence(correlation_attempt_id);

-- ============================================================
-- finding_evidence_links: Finding 关联明细（组合 FK）
-- ============================================================
CREATE TABLE IF NOT EXISTS finding_evidence_links (
    finding_evidence_id TEXT NOT NULL REFERENCES finding_evidence(finding_evidence_id) ON DELETE CASCADE,
    correlation_attempt_id TEXT NOT NULL,
    endpoint_evidence_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    execution_flow_id TEXT,
    relation_type TEXT NOT NULL DEFAULT 'UNKNOWN',
    call_distance INTEGER,
    PRIMARY KEY (finding_evidence_id, endpoint_evidence_id, endpoint_id, relation_type),
    FOREIGN KEY (correlation_attempt_id, endpoint_evidence_id)
        REFERENCES endpoint_evidence(correlation_attempt_id, endpoint_evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_fel_finding_evidence ON finding_evidence_links(finding_evidence_id);

-- ============================================================
-- correlation_attempt_reasons: Partial 原因明细
-- ============================================================
CREATE TABLE IF NOT EXISTS correlation_attempt_reasons (
    correlation_attempt_id TEXT NOT NULL REFERENCES correlation_attempts(correlation_attempt_id) ON DELETE CASCADE,
    reason_code TEXT NOT NULL
        CHECK (reason_code IN ('CAPTURE_TRUNCATED','REQUEST_PERSISTENCE_FAILED',
               'WHITEBOX_PARTIAL','SOURCE_MISMATCH_OVERRIDE')),
    detail TEXT,
    PRIMARY KEY (correlation_attempt_id, reason_code)
);

-- ============================================================
-- correlation_attempt_diagnostics: 诊断明细
-- ============================================================
CREATE TABLE IF NOT EXISTS correlation_attempt_diagnostics (
    correlation_attempt_id TEXT NOT NULL REFERENCES correlation_attempts(correlation_attempt_id) ON DELETE CASCADE,
    diagnostic_code TEXT NOT NULL
        CHECK (diagnostic_code IN ('REGEX_CONSTRAINT_NOT_PORTABLE','REGEX_COMPILE_FAILED_FALLBACK',
               'NO_ELIGIBLE_REQUESTS','PATH_MAPPING_APPLIED')),
    detail TEXT,
    PRIMARY KEY (correlation_attempt_id, diagnostic_code)
);
