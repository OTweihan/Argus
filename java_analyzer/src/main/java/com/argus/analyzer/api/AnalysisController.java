package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.service.AnalysisJobService;
import com.argus.analyzer.service.ProjectAnalyzerService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.NoSuchElementException;

@RestController
@RequestMapping("/argus/api")
public class AnalysisController {

    private final ProjectAnalyzerService analyzerService;
    private final AnalysisJobService jobService;

    public AnalysisController(ProjectAnalyzerService analyzerService, AnalysisJobService jobService) {
        this.analyzerService = analyzerService;
        this.jobService = jobService;
    }

    @PostMapping("/analyze")
    public AnalyzeResponse analyze(@Valid @RequestBody AnalyzeRequest request) {
        return analyzerService.analyze(request);
    }

    @PostMapping("/analyze/jobs")
    public AnalysisJobStatusResponse submitJob(@Valid @RequestBody AnalyzeRequest request) {
        return jobService.submit(request);
    }

    @GetMapping("/analyze/jobs/{jobId}")
    public AnalysisJobStatusResponse getJob(@PathVariable String jobId) {
        try {
            return jobService.getStatus(jobId);
        } catch (NoSuchElementException e) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, e.getMessage(), e);
        }
    }

    @GetMapping("/analyze/jobs/{jobId}/result")
    public AnalyzeResponse getJobResult(@PathVariable String jobId) {
        try {
            return jobService.getResult(jobId);
        } catch (NoSuchElementException e) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, e.getMessage(), e);
        } catch (IllegalStateException e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, e.getMessage(), e);
        }
    }
}
