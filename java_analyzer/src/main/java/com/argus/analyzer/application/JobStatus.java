package com.argus.analyzer.application;

import java.time.Instant;
import java.util.List;

/**
 * 作业状态快照（应用层模型，J1）。
 *
 * <p>{@link #status} 为 CAS 状态机终态词汇（PENDING/RUNNING/SUCCEEDED/FAILED/
 * CANCELLED/TIMED_OUT）。由 {@code AnalysisJobService} 产出、HTTP adapter
 * 经 Mapper 拷贝为 {@code api.dto.AnalysisJobStatusResponse}；应用编排层
 * 不依赖 HTTP wire DTO，作业状态模型可脱离 Spring 单测。</p>
 */
public record JobStatus(
        String jobId,
        String status,
        String stage,
        Instant createdAt,
        Instant startedAt,
        Instant finishedAt,
        String error,
        List<JobEvent> events
) {}
