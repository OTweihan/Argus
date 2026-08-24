package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisProgressListener;

/**
 * 把作业级取消状态桥接到 {@link AnalysisProgressListener} 的 isCancelled()
 * （J5 自 AnalysisJobService 提为包内独立类）。
 */
class JobProgress implements AnalysisProgressListener {
    private final AnalysisJob job;

    JobProgress(AnalysisJob job) {
        this.job = job;
    }

    @Override
    public void onEvent(String stage, String level, String message) {
        job.addEvent(stage, level, message);
    }

    @Override
    public boolean isCancelled() {
        return job.isCancelRequested();
    }
}
