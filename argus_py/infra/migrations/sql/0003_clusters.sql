-- 0003: 功能聚类持久化
-- analysis_clusters 投影表，供控制台聚类页签展示

CREATE TABLE IF NOT EXISTS analysis_clusters (
    cluster_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    suggested_label TEXT NOT NULL DEFAULT '',
    member_keys_json TEXT NOT NULL DEFAULT '[]',
    member_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_clusters_analysis
    ON analysis_clusters(analysis_id);
