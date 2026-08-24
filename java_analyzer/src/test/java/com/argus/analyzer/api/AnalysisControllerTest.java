package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.ValidateSourceRequest;
import com.argus.analyzer.application.JobStatus;
import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.service.AnalysisJobService;
import com.argus.analyzer.service.ProjectAnalyzerService;
import com.argus.analyzer.support.SourceLocator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.HttpStatus;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.concurrent.RejectedExecutionException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AnalysisControllerTest {

    private static AnalysisController controllerWith(ProjectAnalyzerService analyzer,
                                                     AnalysisJobService jobs) {
        // 默认使用宽松模式 SourceLocator（不限制根目录），便于单测聚焦 Controller 逻辑。
        return new AnalysisController(analyzer, jobs, new SourceLocator());
    }

    @Test
    void shouldPropagateQueueRejectionToGlobalHandler(@TempDir Path sourceDir) {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        AnalyzeRequest request = new AnalyzeRequest(sourceDir.toString(), "all");
        when(jobs.submit(any(AnalysisCommand.class), any()))
                .thenThrow(new RejectedExecutionException("full"));
        AnalysisController controller = controllerWith(analyzer, jobs);

        // 异常映射统一在 AnalysisExceptionHandler（J3）；Controller 原样向上传播。
        assertThatThrownBy(() -> controller.submitJob(request))
                .isInstanceOf(RejectedExecutionException.class);
    }

    @Test
    void shouldMapAnyRejectedExecutionToServiceUnavailable() {
        var detail = new AnalysisExceptionHandler()
                .handleRejectedExecution(new RejectedExecutionException("full"));

        assertThat(detail.getStatus()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE.value());
        assertThat(detail.getDetail()).doesNotContain("full");
    }

    @Test
    void shouldMapIdempotencyConflictToConflict() {
        var detail = new AnalysisExceptionHandler().handleIdempotencyConflict(
                new AnalysisJobService.IdempotencyConflictException("task-1:1"));

        assertThat(detail.getStatus()).isEqualTo(HttpStatus.CONFLICT.value());
        assertThat(detail.getDetail()).contains("task-1:1");
    }

    @Test
    void shouldMapMissingJobToNotFound() {
        var detail = new AnalysisExceptionHandler().handleNotFound(
                new NoSuchElementException("Analysis job not found: gone"));

        assertThat(detail.getStatus()).isEqualTo(HttpStatus.NOT_FOUND.value());
        assertThat(detail.getDetail()).contains("gone");
    }

    @Test
    void shouldMapIncompleteJobResultToConflict() {
        var detail = new AnalysisExceptionHandler().handleJobNotComplete(
                new AnalysisJobService.JobNotCompleteException("Analysis job is not complete: CANCELLED"));

        assertThat(detail.getStatus()).isEqualTo(HttpStatus.CONFLICT.value());
        assertThat(detail.getDetail()).contains("CANCELLED");
    }

    @Test
    void shouldCancelJob() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        JobStatus cancelled = new JobStatus(
                "job-1", "CANCELLED", "cancelled",
                Instant.now(), Instant.now(), Instant.now(), null, List.of());
        when(jobs.cancel("job-1")).thenReturn(cancelled);
        AnalysisController controller = controllerWith(analyzer, jobs);

        // Controller 负责把应用层状态映射为 wire DTO（J1）
        AnalysisJobStatusResponse expected = AnalysisJobStatusMapper.map(cancelled);
        assertThat(controller.cancelJob("job-1")).isEqualTo(expected);
    }

    @Test
    void shouldPropagateCancelMissingToGlobalHandler() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        when(jobs.cancel("gone")).thenThrow(new NoSuchElementException("not found"));
        AnalysisController controller = controllerWith(analyzer, jobs);

        assertThatThrownBy(() -> controller.cancelJob("gone"))
                .isInstanceOf(NoSuchElementException.class);
    }

    @Test
    void shouldValidateReadableSourceDirectory(@TempDir Path sourceDir) {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        AnalysisController controller = controllerWith(analyzer, jobs);

        var result = controller.validateSource(new ValidateSourceRequest(sourceDir.toString()));

        assertThat(result).containsEntry("exists", true)
                .containsEntry("readable", true)
                .containsEntry("allowed", true);
    }

    @Test
    void shouldReportAllowedFalseWhenOutsideRoots(@TempDir Path sourceDir, @TempDir Path otherDir)
            throws Exception {
        Files.writeString(sourceDir.resolve("App.java"), "class App {}");
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        // 只允许 otherDir：sourceDir 在允许根目录之外。
        SourceLocator strict = new SourceLocator(otherDir.toString());
        AnalysisController controller = new AnalysisController(analyzer, jobs, strict);

        var result = controller.validateSource(new ValidateSourceRequest(sourceDir.toString()));

        // allowed root 外路径不泄露存在性或可读性。
        assertThat(result).containsEntry("exists", false)
                .containsEntry("readable", false)
                .containsEntry("allowed", false);
    }
}
