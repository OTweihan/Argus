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
import org.springframework.web.bind.annotation.DeleteMapping;
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
        // 先执行与 analyze 相同的 real-path/allowed-roots 校验，再暴露存在性与
        // 可读性。根目录外、符号链接逃逸和不存在路径统一返回全 false，避免该
        // 内部诊断端点在端口误开放时沦为任意路径存在性探针。
        try {
            Path path = sourceLocator.resolveForAnalysis(request.sourcePath());
            boolean readable = Files.isReadable(path);
            return Map.of("exists", true, "readable", readable, "allowed", readable);
        } catch (IllegalArgumentException error) {
            return Map.of("exists", false, "readable", false, "allowed", false);
        }
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

    /**
     * 幂等协作取消（O-04）：PENDING/RUNNING 作业请求取消，已终态则返回当前状态。
     */
    @DeleteMapping("/analyze/jobs/{jobId}")
    public AnalysisJobStatusResponse cancelJob(@PathVariable String jobId) {
        try {
            return jobService.cancel(jobId);
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
