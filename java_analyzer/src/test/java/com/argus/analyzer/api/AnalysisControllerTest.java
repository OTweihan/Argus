package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.ValidateSourceRequest;
import com.argus.analyzer.service.AnalysisJobService;
import com.argus.analyzer.service.ProjectAnalyzerService;
import com.argus.analyzer.support.SourceLocator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.RejectedExecutionException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AnalysisControllerTest {

    private static AnalysisController controllerWith(ProjectAnalyzerService analyzer,
                                                     AnalysisJobService jobs) {
        // 默认使用宽松模式 SourceLocator（不限制根目录），便于单测聚焦 Controller 逻辑。
        return new AnalysisController(analyzer, jobs, new SourceLocator());
    }

    @Test
    void shouldPropagateQueueRejectionToGlobalHandler() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        AnalyzeRequest request = new AnalyzeRequest("C:\\project", "all");
        when(jobs.submit(request)).thenThrow(new RejectedExecutionException("full"));
        AnalysisController controller = controllerWith(analyzer, jobs);

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
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        AnalyzeRequest request = new AnalyzeRequest(
                "C:\\project", "all", null, null, "task-1:1");
        when(jobs.submit(request)).thenThrow(
                new AnalysisJobService.IdempotencyConflictException("task-1:1"));
        AnalysisController controller = controllerWith(analyzer, jobs);

        assertThatThrownBy(() -> controller.submitJob(request))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode()).isEqualTo(HttpStatus.CONFLICT));
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
