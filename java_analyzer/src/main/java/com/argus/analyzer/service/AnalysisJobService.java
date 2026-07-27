package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.AnalysisJobEvent;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.env.MavenConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

@Service
public class AnalysisJobService {

    private static final int MAX_EVENTS = 200;
    private static final Logger log = LoggerFactory.getLogger(AnalysisJobService.class);

    private final ProjectAnalyzerService analyzerService;
    private final Map<String, AnalysisJob> jobs = new ConcurrentHashMap<>();
    private final Map<String, IdempotencyEntry> idempotencyEntries = new ConcurrentHashMap<>();
    private final Executor jobExecutor;
    private final int maxJobs;
    private final long retentionSeconds;

    public AnalysisJobService(ProjectAnalyzerService analyzerService,
                              @Qualifier("analysisJobExecutor") Executor jobExecutor,
                              @Value("${argus.analysis.jobs.max-entries:1000}") int maxJobs,
                              @Value("${argus.analysis.jobs.retention-seconds:1800}") long retentionSeconds) {
        this.analyzerService = analyzerService;
        this.jobExecutor = jobExecutor;
        this.maxJobs = Math.max(1, maxJobs);
        this.retentionSeconds = Math.max(1, retentionSeconds);
    }

    public AnalysisJobStatusResponse submit(AnalyzeRequest request) {
        // cleanupExpiredJobs 在 synchronized 外执行——jobs/idempotencyEntries
        // 均为 ConcurrentHashMap，removeIf 自身线程安全；避免锁内遍历阻塞提交
        cleanupExpiredJobs();

        synchronized (this) {
            // 幂等：相同 clientRequestId 返回已有作业
            String requestId = request.clientRequestId();
            RequestFingerprint fingerprint = RequestFingerprint.from(request);
            if (requestId != null && !requestId.isBlank()) {
                IdempotencyEntry entry = idempotencyEntries.get(requestId);
                if (entry != null) {
                    AnalysisJob existingJob = jobs.get(entry.jobId());
                    if (existingJob != null) {
                        if (!entry.fingerprint().equals(fingerprint)) {
                            throw new IdempotencyConflictException(requestId);
                        }
                        log.info("幂等命中 clientRequestId={} → 复用已有作业 {}", requestId, entry.jobId());
                        return existingJob.toStatusResponse();
                    }
                    // 作业已过期清理，移除失效映射
                    idempotencyEntries.remove(requestId);
                }
            }

            if (jobs.size() >= maxJobs) {
                throw new RejectedExecutionException("Analysis job capacity reached: " + maxJobs);
            }
            String jobId = UUID.randomUUID().toString();
            AnalysisJob job = new AnalysisJob(jobId);
            jobs.put(jobId, job);

            if (requestId != null && !requestId.isBlank()) {
                idempotencyEntries.put(requestId, new IdempotencyEntry(jobId, fingerprint));
            }

            try {
                jobExecutor.execute(() -> runJob(job, request));
            } catch (RejectedExecutionException error) {
                jobs.remove(jobId);
                if (requestId != null) {
                    idempotencyEntries.remove(requestId);
                }
                throw error;
            }
            return job.toStatusResponse();
        }
    }

    @Scheduled(fixedDelayString = "${argus.analysis.jobs.cleanup-interval-ms:60000}")
    public void cleanupExpiredJobs() {
        Instant cutoff = Instant.now().minusSeconds(retentionSeconds);
        jobs.entrySet().removeIf(entry -> {
            if (entry.getValue().finishedBefore(cutoff)) {
                // 同步清理幂等映射
                idempotencyEntries.values().removeIf(item -> item.jobId().equals(entry.getKey()));
                return true;
            }
            return false;
        });
        // 清理孤立幂等条目（作业已不存在或条目超时未关联有效作业）
        idempotencyEntries.entrySet().removeIf(entry -> {
            AnalysisJob job = jobs.get(entry.getValue().jobId());
            if (job != null) {
                return false;  // 作业仍存在
            }
            // 作业不存在且条目超过 retention 时间 → 清理
            return entry.getValue().createdAt().isBefore(cutoff);
        });
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

    public static class IdempotencyConflictException extends RuntimeException {
        public IdempotencyConflictException(String clientRequestId) {
            super("clientRequestId already exists with different parameters: " + clientRequestId);
        }
    }

    private record IdempotencyEntry(String jobId, RequestFingerprint fingerprint, Instant createdAt) {
        IdempotencyEntry(String jobId, RequestFingerprint fingerprint) {
            this(jobId, fingerprint, Instant.now());
        }
    }

    private record RequestFingerprint(
            String sourcePath,
            String scope,
            List<String> targetModules,
            MavenFingerprint maven
    ) {
        private static RequestFingerprint from(AnalyzeRequest request) {
            List<String> modules = request.targetModules() == null
                    ? List.of()
                    : List.copyOf(request.targetModules());
            return new RequestFingerprint(
                    request.sourcePath(),
                    request.scope(),
                    modules,
                    MavenFingerprint.from(request.maven())
            );
        }
    }

    private record MavenFingerprint(
            boolean autoDetect,
            boolean generateClasspath,
            String classpathFile,
            String executable,
            String settingsXml,
            String localRepository,
            boolean offline,
            String dependencyPluginVersion,
            long offlineTimeoutSeconds,
            long onlineTimeoutSeconds,
            String classpathMode,
            boolean prepareReactorArtifacts
    ) {
        private static MavenFingerprint from(MavenConfig config) {
            if (config == null) {
                return null;
            }
            return new MavenFingerprint(
                    config.isAutoDetect(),
                    config.isGenerateClasspath(),
                    config.getClasspathFile(),
                    config.getExecutable(),
                    config.getSettingsXml(),
                    config.getLocalRepository(),
                    config.isOffline(),
                    config.getDependencyPluginVersion(),
                    config.getOfflineTimeoutSeconds(),
                    config.getOnlineTimeoutSeconds(),
                    config.getClasspathMode() == null ? null : config.getClasspathMode().name(),
                    config.isPrepareReactorArtifacts()
            );
        }
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

        private int eventSequence = 0;

        private synchronized void addEvent(String stage, String level, String message) {
            this.stage = stage;
            int seq = eventSequence++;
            String eventId = UUID.randomUUID().toString();
            events.addLast(new AnalysisJobEvent(Instant.now(), stage, level, message, seq, eventId));
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

        private synchronized boolean finishedBefore(Instant cutoff) {
            return finishedAt != null && finishedAt.isBefore(cutoff);
        }
    }
}
