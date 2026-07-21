package com.argus.analyzer.api.dto;

import java.time.Instant;
import java.util.List;

public record AnalysisJobStatusResponse(
    String jobId,
    String status,
    String stage,
    Instant createdAt,
    Instant startedAt,
    Instant finishedAt,
    String error,
    List<AnalysisJobEvent> events
) {}
