package com.argus.analyzer.api.dto;

import java.time.Instant;

public record AnalysisJobEvent(Instant timestamp, String stage, String level, String message) {}
