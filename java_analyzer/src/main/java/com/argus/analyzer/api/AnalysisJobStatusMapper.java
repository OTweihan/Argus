package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalysisJobEvent;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.application.JobStatus;

import java.util.List;

/**
 * 应用层 {@link JobStatus} → HTTP wire {@link AnalysisJobStatusResponse} 映射（J1）。
 *
 * <p>作业状态/事件模型为应用层共享类型，映射为纯字段拷贝；HTTP adapter 是
 * 唯一产出 wire DTO 的地方。</p>
 */
public final class AnalysisJobStatusMapper {

    private AnalysisJobStatusMapper() {}

    public static AnalysisJobStatusResponse map(JobStatus status) {
        if (status == null) {
            return null;
        }
        List<AnalysisJobEvent> events = status.events().stream()
                .map(event -> new AnalysisJobEvent(
                        event.timestamp(),
                        event.stage(),
                        event.level(),
                        event.message(),
                        event.sequence(),
                        event.eventId()))
                .toList();
        return new AnalysisJobStatusResponse(
                status.jobId(),
                status.status(),
                status.stage(),
                status.createdAt(),
                status.startedAt(),
                status.finishedAt(),
                status.error(),
                events
        );
    }
}
