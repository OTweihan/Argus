package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.api.dto.ValidateSourceRequest;
import com.argus.analyzer.service.AnalysisJobService;
import com.argus.analyzer.service.ProjectAnalyzerService;
import com.argus.analyzer.support.SourceLocator;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.NoSuchElementException;

@RestController
@RequestMapping("/argus/api")
public class AnalysisController {

    private final ProjectAnalyzerService analyzerService;
    private final AnalysisJobService jobService;
    private final SourceLocator sourceLocator;

    public AnalysisController(ProjectAnalyzerService analyzerService, AnalysisJobService jobService,
                              SourceLocator sourceLocator) {
        this.analyzerService = analyzerService;
        this.jobService = jobService;
        this.sourceLocator = sourceLocator;
    }

    @PostMapping("/analyze")
    public AnalyzeResponse analyze(@Valid @RequestBody AnalyzeRequest request) {
        return analyzerService.analyze(request);
    }

    @PostMapping("/analyze/validate-source")
    public Map<String, Boolean> validateSource(@Valid @RequestBody ValidateSourceRequest request) {
        Path path = Path.of(request.sourcePath());
        boolean exists = Files.exists(path);
        boolean readable = exists && Files.isReadable(path);
        // 与 analyze 统一复用 real-path 边界校验器：allowed-source-roots +
        // 符号链接逃逸均在此判定，探测接口不抛异常，由调用方决定是否阻断。
        boolean allowed = false;
        if (exists && readable) {
            try {
                sourceLocator.resolveForAnalysis(request.sourcePath());
                allowed = true;
            } catch (IllegalArgumentException error) {
                allowed = false;
            }
        }
        return Map.of("exists", exists, "readable", readable, "allowed", allowed);
    }

    @PostMapping("/analyze/jobs")
    public AnalysisJobStatusResponse submitJob(@Valid @RequestBody AnalyzeRequest request) {
        try {
            return jobService.submit(request);
        } catch (AnalysisJobService.IdempotencyConflictException e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, e.getMessage(), e);
        }
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
