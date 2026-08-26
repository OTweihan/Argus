-- 0007: 项目级回归测试闭环（regression_cases / regression_runs / regression_run_items）
-- 全部使用 IF NOT EXISTS，可安全重放；由 schema_migrations 版本机制保证仅执行一次。
-- 设计见 docs/optimizations/regression-test-closed-loop-plan.md。

CREATE TABLE IF NOT EXISTS regression_cases (
  case_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  name TEXT NOT NULL,
  task_type TEXT NOT NULL,
  goal TEXT NOT NULL,
  start_url TEXT,
  max_steps INTEGER NOT NULL,
  timeout_seconds INTEGER NOT NULL,
  capture_screenshots INTEGER NOT NULL DEFAULT 1,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  whitebox_config_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regression_cases_project
    ON regression_cases(project_id, display_order);

CREATE TABLE IF NOT EXISTS regression_runs (
  run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  trigger_source TEXT NOT NULL DEFAULT 'api',
  triggered_by TEXT,
  -- 创建时固定的对比基线批次；NULL 表示首跑无对比
  baseline_run_id TEXT REFERENCES regression_runs(run_id),
  status TEXT NOT NULL DEFAULT 'pending',
  gate_result TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}',
  is_baseline INTEGER NOT NULL DEFAULT 0,
  error_code TEXT,
  error_message TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regression_runs_project
    ON regression_runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_regression_runs_status
    ON regression_runs(status);

CREATE TABLE IF NOT EXISTS regression_run_items (
  item_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES regression_runs(run_id) ON DELETE CASCADE,
  case_id TEXT NOT NULL,
  case_name TEXT NOT NULL DEFAULT '',
  display_order INTEGER NOT NULL DEFAULT 0,
  case_snapshot_json TEXT NOT NULL DEFAULT '{}',
  -- 子任务；tasks 行被删除时置空（批次项转 skipped 由应用层恢复处理）
  task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  finding_count INTEGER,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regression_items_run
    ON regression_run_items(run_id, display_order);
CREATE INDEX IF NOT EXISTS idx_regression_items_task
    ON regression_run_items(task_id) WHERE task_id IS NOT NULL;

-- 每个项目至多一个基线批次：仅成功批次允许显式设置（应用层校验），
-- 部分唯一索引在存储层兜底并发写入。
CREATE UNIQUE INDEX IF NOT EXISTS uq_regression_baseline_per_project
    ON regression_runs(project_id) WHERE is_baseline = 1;
