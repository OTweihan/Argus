package com.argus.analyzer.service;

import com.argus.analyzer.application.JobEvent;
import com.argus.analyzer.application.JobStatus;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.AnalysisResult;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.UUID;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 单个分析作业的 CAS 状态机（J5 自 {@link AnalysisJobService} 提为包内独立类）。
 *
 * <p>终态由 {@link #status} 的 CAS 单向前进决定。取消/完成/超时并发时，
 * 先抢占到终态者生效，其余 no-op——由此定义“完成先发生”与“取消先发生”
 * 的确定结果。</p>
 *
 * <p>成员为包内可见：{@code AnalysisJobService} 负责编排（提交/取消/deadline/
 * 事件记录），本类只维护状态迁移与其派生快照。</p>
 */
class AnalysisJob {

    private static final int MAX_EVENTS = 200;

    final String jobId;
    final Instant deadline;

    private final Instant createdAt = Instant.now();
    private final Deque<JobEvent> events = new ArrayDeque<>();
    private final AtomicReference<String> status = new AtomicReference<>("PENDING");
    private final AtomicBoolean cancelRequested = new AtomicBoolean(false);
    private final AnalysisProgressListener progress = new JobProgress(this);

    private volatile String stage = "queued";
    private volatile Instant startedAt;
    private volatile Instant finishedAt;
    private volatile String error;
    volatile AnalysisResult result;
    volatile Future<?> future;

    AnalysisJob(String jobId, Instant deadline) {
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

    boolean markFailed(Throwable t) {
        if (status.compareAndSet("PENDING", "FAILED") || status.compareAndSet("RUNNING", "FAILED")) {
            stage = "failed";
            error = t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
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

    synchronized void addEvent(String stage, String level, String message) {
        this.stage = stage;
        int seq = eventSequence++;
        String eventId = UUID.randomUUID().toString();
        events.addLast(new JobEvent(Instant.now(), stage, level, message, seq, eventId));
        while (events.size() > MAX_EVENTS) {
            events.removeFirst();
        }
    }

    /** 产出应用层状态快照；wire DTO 由 HTTP adapter 经 Mapper 拷贝（J1）。 */
    synchronized JobStatus snapshot() {
        return new JobStatus(
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

    synchronized AnalysisResult getResult() {
        if (!"SUCCEEDED".equals(status.get())) {
            throw new AnalysisJobService.JobNotCompleteException(
                    "Analysis job is not complete: " + status.get());
        }
        return result;
    }

    boolean finishedBefore(Instant cutoff) {
        return finishedAt != null && finishedAt.isBefore(cutoff);
    }
}
