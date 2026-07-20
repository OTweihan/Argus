package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.AnalysisJobEvent;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class AnalysisJobService {

    private static final int MAX_EVENTS = 200;
    private static final Logger log = LoggerFactory.getLogger(AnalysisJobService.class);

    private final ProjectAnalyzerService analyzerService;
    private final Map<String, AnalysisJob> jobs = new ConcurrentHashMap<>();

    public AnalysisJobService(ProjectAnalyzerService analyzerService) {
        this.analyzerService = analyzerService;
    }

    public AnalysisJobStatusResponse submit(AnalyzeRequest request) {
        String jobId = UUID.randomUUID().toString();
        AnalysisJob job = new AnalysisJob(jobId);
        jobs.put(jobId, job);

        CompletableFuture.runAsync(() -> runJob(job, request));
        return job.toStatusResponse();
    }

    public AnalysisJobStatusResponse getStatus(String jobId) {
        return getJob(jobId).toStatusResponse();
    }

    public AnalyzeResponse getResult(String jobId) {
        return getJob(jobId).getResult();
    }

    private void runJob(AnalysisJob job, AnalyzeRequest request) {
        job.markRunning();
        job.addEvent("analysis", "INFO", "Analysis job started");
        try {
            AnalyzeResponse response = analyzerService.analyze(request, job::addEvent);
            job.result = response;
            job.addEvent("analysis", "INFO", "Analysis job completed");
            job.markSucceeded();
        } catch (Exception e) {
            log.error("Analysis job {} failed: {}", job.jobId, e.getMessage(), e);
            job.addEvent("analysis", "ERROR", e.getMessage());
            job.markFailed(e);
        }
    }

    private AnalysisJob getJob(String jobId) {
        AnalysisJob job = jobs.get(jobId);
        if (job == null) {
            throw new NoSuchElementException("Analysis job not found: " + jobId);
        }
        return job;
    }

    private static class AnalysisJob {

        private final String jobId;
        private final Instant createdAt = Instant.now();
        private final Deque<AnalysisJobEvent> events = new ArrayDeque<>();
        private String status = "PENDING";
        private String stage = "queued";
        private Instant startedAt;
        private Instant finishedAt;
        private String error;
        private AnalyzeResponse result;

        private AnalysisJob(String jobId) {
            this.jobId = jobId;
        }

        private synchronized void markRunning() {
            status = "RUNNING";
            stage = "analysis";
            startedAt = Instant.now();
        }

        private synchronized void markSucceeded() {
            status = "SUCCEEDED";
            stage = "complete";
            finishedAt = Instant.now();
        }

        private synchronized void markFailed(Exception e) {
            status = "FAILED";
            stage = "failed";
            error = e.getMessage();
            finishedAt = Instant.now();
        }

        private synchronized void addEvent(String stage, String level, String message) {
            this.stage = stage;
            events.addLast(new AnalysisJobEvent(Instant.now(), stage, level, message));
            while (events.size() > MAX_EVENTS) {
                events.removeFirst();
            }
        }

        private synchronized AnalysisJobStatusResponse toStatusResponse() {
            return new AnalysisJobStatusResponse(
                    jobId,
                    status,
                    stage,
                    createdAt,
                    startedAt,
                    finishedAt,
                    error,
                    new ArrayList<>(events)
            );
        }

        private synchronized AnalyzeResponse getResult() {
            if (!"SUCCEEDED".equals(status)) {
                throw new IllegalStateException("Analysis job is not complete: " + status);
            }
            return result;
        }
    }
}
