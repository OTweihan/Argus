package com.argus.analyzer.service;

import com.argus.analyzer.application.JobStatus;
import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenConfigFingerprint;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.FutureTask;
import java.util.concurrent.RejectedExecutionException;
import java.util.stream.Collectors;

/**
 * 分析作业编排：提交/幂等/cleanup/deadline 兜底与执行边界（J5）。
 *
 * <p>作业状态机见 {@link AnalysisJob}，进度桥接见 {@link JobProgress}；
 * 本类只保留编排与幂等逻辑。</p>
 */
@Service
public class AnalysisJobService {

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

    public JobStatus submit(AnalysisCommand command, MavenConfig mavenConfig) {
        // cleanupExpiredJobs 在 synchronized 外执行——jobs/idempotencyEntries
        // 均为 ConcurrentHashMap，removeIf 自身线程安全；避免锁内遍历阻塞提交
        cleanupExpiredJobs();

        synchronized (this) {
            // 幂等：相同 clientRequestId 返回已有作业
            String requestId = command.clientRequestId();
            RequestFingerprint fingerprint = RequestFingerprint.from(command, mavenConfig);
            if (requestId != null && !requestId.isBlank()) {
                IdempotencyEntry entry = idempotencyEntries.get(requestId);
                if (entry != null) {
                    AnalysisJob existingJob = jobs.get(entry.jobId());
                    if (existingJob != null) {
                        if (!entry.fingerprint().equals(fingerprint)) {
                            throw new IdempotencyConflictException(requestId);
                        }
                        log.info("幂等命中 clientRequestId={} → 复用已有作业 {}", requestId, entry.jobId());
                        return existingJob.snapshot();
                    }
                    // 作业已过期清理，移除失效映射
                    idempotencyEntries.remove(requestId);
                }
            }

            // 容量语义 = 并发作业上限：只统计 PENDING/RUNNING 的活跃作业。
            // 保留期内（retention 默认 1800s）的终态作业仍留在 jobs 表供
            // 状态查询/幂等复用，由 cleanupExpiredJobs 按 TTL 回收，不计入
            // 准入——否则高完成速率下已完成作业会挤占额度，造成假性 503。
            long activeJobs = jobs.values().stream().filter(AnalysisJob::isActive).count();
            if (activeJobs >= maxJobs) {
                throw new RejectedExecutionException(
                        "Analysis job capacity reached: " + maxJobs + " active jobs");
            }
            String jobId = UUID.randomUUID().toString();
            long timeout = resolveTimeoutSeconds(command.timeoutSeconds());
            Instant deadline = Instant.now().plusSeconds(timeout);
            AnalysisJob job = new AnalysisJob(jobId, deadline);
            jobs.put(jobId, job);

            if (requestId != null && !requestId.isBlank()) {
                idempotencyEntries.put(requestId, new IdempotencyEntry(jobId, fingerprint));
            }

            try {
                FutureTask<Void> future = new FutureTask<>(() -> {
                    runJob(job, command, mavenConfig);
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
            return job.snapshot();
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
        // 一次性收集到期 jobId，再对幂等映射做单次 removeIf，避免
        // "对每个到期作业嵌套扫描 idempotencyEntries" 的 O(到期作业数 × 幂等条目数)。
        Set<String> expiredIds = jobs.entrySet().stream()
                .filter(entry -> entry.getValue().finishedBefore(cutoff))
                .map(Map.Entry::getKey)
                .collect(Collectors.toSet());
        if (!expiredIds.isEmpty()) {
            jobs.keySet().removeAll(expiredIds);
            idempotencyEntries.values().removeIf(item -> expiredIds.contains(item.jobId()));
        }
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

    public JobStatus getStatus(String jobId) {
        return getJob(jobId).snapshot();
    }

    public AnalysisResult getResult(String jobId) {
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
    public JobStatus cancel(String jobId) {
        AnalysisJob job = getJob(jobId);
        job.requestCancel();
        // 立即终止该作业名下所有 Maven 进程树（PENDING 时无进程，无害）
        mavenProcessRegistry.destroyFor(job.progress());
        return job.snapshot();
    }

    private void runJob(AnalysisJob job, AnalysisCommand command, MavenConfig mavenConfig) {
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
            AnalysisResult response = analyzerService.analyze(command, mavenConfig, progress);
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
        } catch (Throwable t) {
            // Error（OOM/StackOverflow/AssertionError 等）也在作业边界收敛到终态，
            // 避免作业停在 RUNNING 直到 deadline 兜底。PassExecutor 语义上 Error
            // 原样传播，此处只负责把终态与错误信息记录在作业边界。
            String message = t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
            log.error("Analysis job {} failed: {}", job.jobId, message, t);
            job.addEvent("analysis", "ERROR", message);
            job.markFailed(t);
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

    /**
     * 结果未就绪：作业未到 SUCCEEDED 即请求结果（J3）。
     * 继承 {@link IllegalStateException} 保持既有捕获语义，同时让全局异常
     * 处理器能把它与基础设施层的 IllegalStateException（应映射 500）区分开，
     * 精确映射为 409。
     */
    public static class JobNotCompleteException extends IllegalStateException {
        public JobNotCompleteException(String message) {
            super(message);
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
            MavenFingerprint maven,
            String sourceRevision,
            String snapshotDigest
    ) {
        private static RequestFingerprint from(AnalysisCommand command, MavenConfig mavenConfig) {
            return new RequestFingerprint(
                    command.sourcePath().toString(),
                    command.scope().wireValue(),
                    List.copyOf(command.targetModules()),
                    MavenFingerprint.from(mavenConfig),
                    command.sourceRevision(),
                    command.snapshotDigest()
            );
        }
    }

    private record MavenFingerprint(String fingerprint) {
        private static MavenFingerprint from(MavenConfig config) {
            if (config == null) {
                return null;
            }
            // 与 ProjectIndexCache 的缓存键共用同一份 MavenConfig 规范化指纹，
            // 消除两处此前 settingsXml（内容哈希 vs 路径）与空值处理不一致导致的
            // 「幂等判定为同请求却产生不同缓存键」矛盾。
            return new MavenFingerprint(MavenConfigFingerprint.fingerprint(config));
        }
    }
}
