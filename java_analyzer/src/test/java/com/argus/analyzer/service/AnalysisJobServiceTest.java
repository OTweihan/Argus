package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
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
}
