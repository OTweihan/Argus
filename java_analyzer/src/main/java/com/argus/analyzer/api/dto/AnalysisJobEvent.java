package com.argus.analyzer.api.dto;

import java.time.Instant;

public class AnalysisJobEvent {

    private Instant timestamp;
    private String stage;
    private String level;
    private String message;

    public AnalysisJobEvent() {}

    public AnalysisJobEvent(Instant timestamp, String stage, String level, String message) {
        this.timestamp = timestamp;
        this.stage = stage;
        this.level = level;
        this.message = message;
    }

    public Instant getTimestamp() { return timestamp; }
    public void setTimestamp(Instant timestamp) { this.timestamp = timestamp; }

    public String getStage() { return stage; }
    public void setStage(String stage) { this.stage = stage; }

    public String getLevel() { return level; }
    public void setLevel(String level) { this.level = level; }

    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
}
