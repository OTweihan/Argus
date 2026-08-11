package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AnalysisJobServiceTest {

    private final AnalyzeRequest request = new AnalyzeRequest("C:\\project", "all");
    private final AnalyzeResponse response = new AnalyzeResponse(
            List.of(), Map.of(), List.of(), List.of(), List.of(), null);

    @Test
    void shouldRejectWhenExecutorQueueIsFull() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        Executor rejecting = command -> {
            throw new RejectedExecutionException("full");
        };
        AnalysisJobService service = new AnalysisJobService(analyzer, rejecting, 10, 1800);

        assertThatThrownBy(() -> service.submit(request))
                .isInstanceOf(RejectedExecutionException.class)
                .hasMessage("full");
    }

    @Test
    void shouldRejectWhenJobCapacityIsReached() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        List<Runnable> queued = new ArrayList<>();
        AnalysisJobService service = new AnalysisJobService(analyzer, queued::add, 1, 1800);

        service.submit(request);

        assertThatThrownBy(() -> service.submit(request))
                .isInstanceOf(RejectedExecutionException.class)
                .hasMessageContaining("capacity reached");
        assertThat(queued).hasSize(1);
    }

    @Test
    void shouldRetainFailureAsDeterministicJobStatus() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        when(analyzer.analyze(any(), any())).thenThrow(new IllegalStateException("analysis failed"));
        AnalysisJobService service = new AnalysisJobService(analyzer, Runnable::run, 10, 1800);

        var submitted = service.submit(request);
        var status = service.getStatus(submitted.jobId());

        assertThat(status.status()).isEqualTo("FAILED");
        assertThat(status.error()).isEqualTo("analysis failed");
        assertThat(status.events()).isNotEmpty();
        assertThat(status.events()).extracting(event -> event.sequence()).doesNotHaveDuplicates();
        assertThat(status.events()).allMatch(event -> event.eventId() != null);
        assertThatThrownBy(() -> service.getResult(submitted.jobId()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void shouldRemoveOnlyCompletedJobsAfterRetention() throws Exception {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        when(analyzer.analyze(any(), any())).thenReturn(response);
        AnalysisJobService service = new AnalysisJobService(analyzer, Runnable::run, 10, 1);
        var submitted = service.submit(request);

        Thread.sleep(1100);
        service.cleanupExpiredJobs();

        assertThatThrownBy(() -> service.getStatus(submitted.jobId()))
                .isInstanceOf(NoSuchElementException.class);
    }

    @Test
    void shouldReuseJobForSameClientRequestIdAndParameters() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        List<Runnable> queued = new ArrayList<>();
        AnalysisJobService service = new AnalysisJobService(analyzer, queued::add, 10, 1800);
        AnalyzeRequest idempotent = new AnalyzeRequest(
                "C:\\project", "all", List.of("module-a"), null, "task-1:1");

        var first = service.submit(idempotent);
        var second = service.submit(idempotent);

        assertThat(second.jobId()).isEqualTo(first.jobId());
        assertThat(queued).hasSize(1);
    }

    @Test
    void shouldRejectSameClientRequestIdWithDifferentParameters() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        List<Runnable> queued = new ArrayList<>();
        AnalysisJobService service = new AnalysisJobService(analyzer, queued::add, 10, 1800);
        service.submit(new AnalyzeRequest(
                "C:\\project", "all", List.of("module-a"), null, "task-1:1"));

        assertThatThrownBy(() -> service.submit(new AnalyzeRequest(
                "C:\\project", "flows", List.of("module-a"), null, "task-1:1")))
                .isInstanceOf(AnalysisJobService.IdempotencyConflictException.class);
        assertThat(queued).hasSize(1);
    }

    // ── O-04 协作取消 + 服务端 deadline ──────────────────────────────────────

    @Test
    void shouldCancelPendingJobIdempotently() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        List<Runnable> queued = new ArrayList<>();
        AnalysisJobService service = new AnalysisJobService(analyzer, queued::add, 10, 1800);

        var submitted = service.submit(request);

        assertThat(service.cancel(submitted.jobId()).status()).isEqualTo("CANCELLED");
        // 重复取消返回同一终态
        assertThat(service.cancel(submitted.jobId()).status()).isEqualTo("CANCELLED");
        // 排队任务最终执行时不再调用 analyzer
        queued.forEach(Runnable::run);
        verify(analyzer, never()).analyze(any(), any());
    }

    @Test
    void shouldCancelRunningJobWhenAnalyzerObservesCancellation() throws Exception {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            AnalysisJobService service = new AnalysisJobService(analyzer, executor, 10, 1800);
            CountDownLatch started = new CountDownLatch(1);
            CountDownLatch release = new CountDownLatch(1);
            when(analyzer.analyze(any(), any())).thenAnswer(invocation -> {
                started.countDown();
                release.await(5, TimeUnit.SECONDS);
                throw new JobCancelledException();
            });

            var submitted = service.submit(request);
            assertThat(started.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(service.getStatus(submitted.jobId()).status()).isEqualTo("RUNNING");

            var cancelStatus = service.cancel(submitted.jobId());
            // RUNNING 协作取消：先置位（状态可能仍 RUNNING，等工作线程自省）
            assertThat(cancelStatus.status()).isEqualTo("RUNNING");
            release.countDown();

            awaitStatus(service, submitted.jobId(), "CANCELLED");
            // 取消成功后不能发布成功结果
            assertThatThrownBy(() -> service.getResult(submitted.jobId()))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("CANCELLED");
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void shouldDiscardResultWhenCancelledBeforeSucceed() throws Exception {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            AnalysisJobService service = new AnalysisJobService(analyzer, executor, 10, 1800);
            CountDownLatch started = new CountDownLatch(1);
            CountDownLatch release = new CountDownLatch(1);
            when(analyzer.analyze(any(), any())).thenAnswer(invocation -> {
                started.countDown();
                release.await(5, TimeUnit.SECONDS);
                // 分析返回成功响应前先被取消 → 结果必须丢弃
                return response;
            });

            var submitted = service.submit(request);
            assertThat(started.await(5, TimeUnit.SECONDS)).isTrue();

            // 在工作线程落 SUCCEEDED 之前先取消（取消先发生）
            service.cancel(submitted.jobId());
            release.countDown();

            awaitStatus(service, submitted.jobId(), "CANCELLED");
            // 取消成功后不能再发布成功结果
            assertThatThrownBy(() -> service.getResult(submitted.jobId()))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("CANCELLED");
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void shouldMarkTimedOutWhenDeadlineExceeded() throws Exception {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            AnalysisJobService service = new AnalysisJobService(analyzer, executor, 10, 1800);
            CountDownLatch started = new CountDownLatch(1);
            when(analyzer.analyze(any(), any())).thenAnswer(invocation -> {
                started.countDown();
                Thread.sleep(Long.MAX_VALUE); // 阻塞在分析中，直到测试终止
                return response;
            });

            AnalyzeRequest timed = new AnalyzeRequest("C:\\project", "all", List.of(), null, null, 1L);
            var submitted = service.submit(timed);
            assertThat(started.await(5, TimeUnit.SECONDS)).isTrue();

            Thread.sleep(1200); // 超过 1s deadline
            service.enforceDeadlines();

            assertThat(service.getStatus(submitted.jobId()).status()).isEqualTo("TIMED_OUT");
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void shouldMarkQueuedJobTimedOutAndPreventItFromRunning() throws Exception {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        List<Runnable> queued = new ArrayList<>();
        AnalysisJobService service = new AnalysisJobService(
                analyzer,
                queued::add,
                10,
                1800,
                new MavenProcessRegistry(),
                1,
                1
        );

        var submitted = service.submit(request);
        assertThat(submitted.status()).isEqualTo("PENDING");

        Thread.sleep(1200); // 超过 1s deadline，但任务仍在执行器队列中
        service.enforceDeadlines();

        assertThat(service.getStatus(submitted.jobId()).status()).isEqualTo("TIMED_OUT");
        queued.forEach(Runnable::run);
        verify(analyzer, never()).analyze(any(), any());
        assertThat(service.cancel(submitted.jobId()).status()).isEqualTo("TIMED_OUT");
    }

    @Test
    void shouldClampRequestedTimeoutToServerCap() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        List<Runnable> queued = new ArrayList<>();
        AnalysisJobService service = new AnalysisJobService(analyzer, queued::add, 10, 1800);

        // 请求 999999s 被 clamp 到 max（3600）；此处只验证不抛且可提交
        AnalyzeRequest huge = new AnalyzeRequest("C:\\project", "all", List.of(), null, null, 999_999L);
        var submitted = service.submit(huge);
        assertThat(submitted.status()).isEqualTo("PENDING");
    }

    private static void awaitStatus(AnalysisJobService service, String jobId, String expected) {
        long deadline = System.currentTimeMillis() + 5_000;
        while (System.currentTimeMillis() < deadline) {
            String status = service.getStatus(jobId).status();
            if (expected.equals(status)) {
                return;
            }
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new AssertionError("Interrupted while awaiting status " + expected, e);
            }
        }
        throw new AssertionError("Job " + jobId + " did not reach " + expected
                + " within 5s; last=" + service.getStatus(jobId).status());
    }
}
