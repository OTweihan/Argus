package com.argus.analyzer.api.dto;

import java.time.Instant;
import java.util.List;

public class AnalysisJobStatusResponse {

    private String jobId;
    private String status;
    private String stage;
    private Instant createdAt;
    private Instant startedAt;
    private Instant finishedAt;
    private String error;
    private List<AnalysisJobEvent> events;

    public AnalysisJobStatusResponse() {}

    public AnalysisJobStatusResponse(String jobId, String status, String stage,
                                     Instant createdAt, Instant startedAt, Instant finishedAt,
                                     String error, List<AnalysisJobEvent> events) {
        this.jobId = jobId;
        this.status = status;
        this.stage = stage;
        this.createdAt = createdAt;
        this.startedAt = startedAt;
        this.finishedAt = finishedAt;
        this.error = error;
        this.events = events;
    }

    public String getJobId() { return jobId; }
    public void setJobId(String jobId) { this.jobId = jobId; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public String getStage() { return stage; }
    public void setStage(String stage) { this.stage = stage; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }

    public Instant getStartedAt() { return startedAt; }
    public void setStartedAt(Instant startedAt) { this.startedAt = startedAt; }

    public Instant getFinishedAt() { return finishedAt; }
    public void setFinishedAt(Instant finishedAt) { this.finishedAt = finishedAt; }

    public String getError() { return error; }
    public void setError(String error) { this.error = error; }

    public List<AnalysisJobEvent> getEvents() { return events; }
    public void setEvents(List<AnalysisJobEvent> events) { this.events = events; }
}
