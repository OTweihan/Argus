package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.AnalysisJobEvent;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.env.MavenConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.UUID;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

@Service
public class AnalysisJobService {

    private static final int MAX_EVENTS = 200;
    private static final Logger log = LoggerFactory.getLogger(AnalysisJobService.class);

    private final ProjectAnalyzerService analyzerService;
    private final Map<String, AnalysisJob> jobs = new ConcurrentHashMap<>();
    private final Map<String, IdempotencyEntry> idempotencyEntries = new ConcurrentHashMap<>();
    private final Executor jobExecutor;
    private final MavenProcessRegistry mavenProcessRegistry;
    private final int maxJobs;
    private final long retentionSeconds;
    private final long defaultTimeoutSeconds;
    private final long maxTimeoutSeconds;

    @Autowired
    public AnalysisJobService(ProjectAnalyzerService analyzerService,
                              @Qualifier("analysisJobExecutor") Executor jobExecutor,
                              @Value("${argus.analysis.jobs.max-entries:1000}") int maxJobs,
                              @Value("${argus.analysis.jobs.retention-seconds:1800}") long retentionSeconds,
                              MavenProcessRegistry mavenProcessRegistry,
                              @Value("${argus.analysis.jobs.default-timeout-seconds:1800}") long defaultTimeoutSeconds,
                              @Value("${argus.analysis.jobs.max-timeout-seconds:3600}") long maxTimeoutSeconds) {
        this.analyzerService = analyzerService;
        this.jobExecutor = jobExecutor;
        this.mavenProcessRegistry = mavenProcessRegistry;
        this.maxJobs = Math.max(1, maxJobs);
        this.retentionSeconds = Math.max(1, retentionSeconds);
        this.defaultTimeoutSeconds = Math.max(1, defaultTimeoutSeconds);
        this.maxTimeoutSeconds = Math.max(this.defaultTimeoutSeconds, maxTimeoutSeconds);
    }

    /** 测试便捷构造：registry 用空实现（NOOP key 自动跳过），deadline 用默认值。 */
    AnalysisJobService(ProjectAnalyzerService analyzerService, Executor jobExecutor,
                       int maxJobs, long retentionSeconds) {
        this(analyzerService, jobExecutor, maxJobs, retentionSeconds,
                new MavenProcessRegistry(), 1800, 3600);
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
            long timeout = resolveTimeoutSeconds(request.timeoutSeconds());
            Instant deadline = Instant.now().plusSeconds(timeout);
            AnalysisJob job = new AnalysisJob(jobId, deadline);
            jobs.put(jobId, job);

            if (requestId != null && !requestId.isBlank()) {
                idempotencyEntries.put(requestId, new IdempotencyEntry(jobId, fingerprint));
            }

            try {
                FutureTask<Void> future = new FutureTask<>(() -> {
                    runJob(job, request);
                    return null;
                });
                // execute() 前登记 Future，确保直接执行器/快速取消也能观察到同一任务。
                job.future = future;
                jobExecutor.execute(future);
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

    private long resolveTimeoutSeconds(Long requested) {
        if (requested == null || requested <= 0) {
            return defaultTimeoutSeconds;
        }
        return Math.max(1, Math.min(maxTimeoutSeconds, requested));
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

    /**
     * 服务端 deadline 兜底（O-04）：Python 断联后，运行中/排队中的作业
     * 超过 deadline 一律置 TIMED_OUT 并协作取消、终止 Maven 进程树。
     */
    @Scheduled(fixedDelayString = "${argus.analysis.jobs.deadline-check-ms:5000}")
    public void enforceDeadlines() {
        Instant now = Instant.now();
        jobs.values().forEach(job -> {
            if (job.isActive() && job.deadline != null && job.deadline.isBefore(now)) {
                log.warn("Analysis job {} exceeded server deadline {}; forcing TIMED_OUT",
                        job.jobId, job.deadline);
                job.requestTimeout();
                mavenProcessRegistry.destroyFor(job.progress());
            }
        });
    }

    public AnalysisJobStatusResponse getStatus(String jobId) {
        return getJob(jobId).toStatusResponse();
    }

    public AnalyzeResponse getResult(String jobId) {
        return getJob(jobId).getResult();
    }

    /**
     * 幂等协作取消（O-04）。
     *
     * <ul>
     *   <li>PENDING：直接落 CANCELLED 并从执行队列移除（不 interrupt，避免启动竞态被误判失败）；</li>
     *   <li>RUNNING：置协作取消令牌 + 立即终止 Maven 进程树，工作线程在安全边界自省落 CANCELLED；</li>
     *   <li>已终态：no-op，返回当前状态（重复取消返回同一终态）。</li>
     * </ul>
     */
    public AnalysisJobStatusResponse cancel(String jobId) {
        AnalysisJob job = getJob(jobId);
        job.requestCancel();
        // 立即终止该作业名下所有 Maven 进程树（PENDING 时无进程，无害）
        mavenProcessRegistry.destroyFor(job.progress());
        return job.toStatusResponse();
    }

    private void runJob(AnalysisJob job, AnalyzeRequest request) {
        AnalysisProgressListener progress = job.progress();
        if (job.isCancelRequested()) {
            job.markCancelled();
            job.addEvent("analysis", "INFO", "Job cancelled before start");
            return;
        }
        if (!job.markRunning()) {
            job.addEvent("analysis", "INFO", "Job skipped: already " + job.status());
            return;
        }
        job.addEvent("analysis", "INFO", "Analysis job started");
        try {
            AnalyzeResponse response = analyzerService.analyze(request, progress);
            if (job.isCancelRequested()) {
                // 取消先发生：丢弃结果，不发布成功
                job.markCancelled();
                job.addEvent("analysis", "INFO", "Analysis job cancelled");
                return;
            }
            job.result = response;
            if (!job.markSucceeded()) {
                // 取消/超时已在返回前抢占终态——禁止发布成功结果
                job.result = null;
                job.addEvent("analysis", "WARN", "Result discarded: job already " + job.status());
                return;
            }
            job.addEvent("analysis", "INFO", "Analysis job completed");
        } catch (JobCancelledException e) {
            job.addEvent("analysis", "INFO", "Analysis job cancelled");
            job.markCancelled();
        } catch (CompletionException e) {
            // CompletableFuture.join() 会把 JobCancelledException 包成 CompletionException
            if (unwrapCancellation(e) != null) {
                job.addEvent("analysis", "INFO", "Analysis job cancelled");
                job.markCancelled();
            } else {
                log.error("Analysis job {} failed: {}", job.jobId, e.getMessage(), e);
                job.addEvent("analysis", "ERROR", e.getMessage());
                job.markFailed(e);
            }
        } catch (Exception e) {
            log.error("Analysis job {} failed: {}", job.jobId, e.getMessage(), e);
            job.addEvent("analysis", "ERROR", e.getMessage());
            job.markFailed(e);
        } finally {
            mavenProcessRegistry.destroyFor(progress);
        }
    }

    private static Throwable unwrapCancellation(Throwable t) {
        Throwable cur = t;
        while (cur != null) {
            if (cur instanceof JobCancelledException) {
                return cur;
            }
            cur = cur.getCause();
        }
        return null;
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

    /**
     * 作业状态机：终态由 {@link #status} 的 CAS 单向前进决定。
     * 取消/完成/超时并发时，先抢占到终态者生效，其余 no-op——
     * 由此定义“完成先发生”与“取消先发生”的确定结果。
     */
    private static class AnalysisJob {

        private final String jobId;
        private final Instant createdAt = Instant.now();
        private final Instant deadline;
        private final Deque<AnalysisJobEvent> events = new ArrayDeque<>();
        private final AtomicReference<String> status = new AtomicReference<>("PENDING");
        private final AtomicBoolean cancelRequested = new AtomicBoolean(false);
        private final AnalysisProgressListener progress = new JobProgress(this);

        private volatile String stage = "queued";
        private volatile Instant startedAt;
        private volatile Instant finishedAt;
        private volatile String error;
        private volatile AnalyzeResponse result;
        private volatile Future<?> future;

        private AnalysisJob(String jobId, Instant deadline) {
            this.jobId = jobId;
            this.deadline = deadline;
        }

        String jobId() {
            return jobId;
        }

        String status() {
            return status.get();
        }

        boolean isActive() {
            String s = status.get();
            return "PENDING".equals(s) || "RUNNING".equals(s);
        }

        boolean isCancelRequested() {
            return cancelRequested.get();
        }

        AnalysisProgressListener progress() {
            return progress;
        }

        /**
         * 幂等请求取消（供 cancel() / enforceDeadlines() 调用）。
         *
         * @return this（链式便于 cancel() 返回状态）
         */
        AnalysisJob requestCancel() {
            cancelRequested.set(true);
            String current = status.get();
            if ("PENDING".equals(current)) {
                Future<?> f = future;
                if (f != null) {
                    // 不 interrupt：避免与“刚启动”竞态时 interrupt 被误吞成 markFailed
                    f.cancel(false);
                }
                markCancelled();
            } else if ("RUNNING".equals(current)) {
                // 协作取消：不 interrupt（JavaParser 不能安全强杀），工作线程在安全边界
                // 自省 isCancelled() 并落 CANCELLED；Maven 进程树由调用方
                // （cancel()/enforceDeadlines()）经 mavenProcessRegistry 立即终止。
                addEvent("analysis", "INFO", "Cancellation requested; stopping at next safe boundary");
            } else {
                // 已终态：no-op，重复取消返回同一终态
            }
            return this;
        }

        /**
         * deadline 到期：设置协作取消令牌，并由 TIMED_OUT 直接抢占终态。
         *
         * <p>不能复用 {@link #requestCancel()}：它会把 PENDING 先推进到
         * CANCELLED，导致后续无法再落 TIMED_OUT。排队 Future 同样需要取消，
         * 确保执行器随后取出该 Future 时不会再运行分析逻辑。</p>
         */
        AnalysisJob requestTimeout() {
            cancelRequested.set(true);
            if ("PENDING".equals(status.get())) {
                Future<?> f = future;
                if (f != null) {
                    f.cancel(false);
                }
            }
            if (markTimedOut()) {
                addEvent("analysis", "WARN", "Job exceeded server deadline");
            }
            return this;
        }

        boolean markRunning() {
            return status.compareAndSet("PENDING", "RUNNING");
        }

        boolean markSucceeded() {
            if (status.compareAndSet("RUNNING", "SUCCEEDED")) {
                stage = "complete";
                finishedAt = Instant.now();
                return true;
            }
            return false;
        }

        boolean markFailed(Exception e) {
            if (status.compareAndSet("PENDING", "FAILED") || status.compareAndSet("RUNNING", "FAILED")) {
                stage = "failed";
                error = e.getMessage();
                finishedAt = Instant.now();
                return true;
            }
            return false;
        }

        boolean markCancelled() {
            if (status.compareAndSet("PENDING", "CANCELLED") || status.compareAndSet("RUNNING", "CANCELLED")) {
                stage = "cancelled";
                finishedAt = Instant.now();
                return true;
            }
            return false;
        }

        boolean markTimedOut() {
            if (status.compareAndSet("PENDING", "TIMED_OUT") || status.compareAndSet("RUNNING", "TIMED_OUT")) {
                stage = "timed_out";
                finishedAt = Instant.now();
                return true;
            }
            return false;
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
                    status.get(),
                    stage,
                    createdAt,
                    startedAt,
                    finishedAt,
                    error,
                    new ArrayList<>(events)
            );
        }

        private synchronized AnalyzeResponse getResult() {
            if (!"SUCCEEDED".equals(status.get())) {
                throw new IllegalStateException("Analysis job is not complete: " + status.get());
            }
            return result;
        }

        private boolean finishedBefore(Instant cutoff) {
            return finishedAt != null && finishedAt.isBefore(cutoff);
        }
    }

    /** 把作业级取消状态桥接到 AnalysisProgressListener 的 isCancelled()。 */
    private static class JobProgress implements AnalysisProgressListener {
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
}
