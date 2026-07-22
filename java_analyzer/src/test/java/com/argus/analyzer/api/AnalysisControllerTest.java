package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.service.AnalysisJobService;
import com.argus.analyzer.service.ProjectAnalyzerService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import java.util.concurrent.RejectedExecutionException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AnalysisControllerTest {

    @Test
    void shouldPropagateQueueRejectionToGlobalHandler() {
        ProjectAnalyzerService analyzer = mock(ProjectAnalyzerService.class);
        AnalysisJobService jobs = mock(AnalysisJobService.class);
        AnalyzeRequest request = new AnalyzeRequest("C:\\project", "all");
        when(jobs.submit(request)).thenThrow(new RejectedExecutionException("full"));
        AnalysisController controller = new AnalysisController(analyzer, jobs);

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
}
