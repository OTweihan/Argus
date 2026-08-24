package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.api.dto.AnalysisJobStatusResponse;
import com.argus.analyzer.api.dto.ValidateSourceRequest;
import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.service.AnalysisJobService;
import com.argus.analyzer.service.ProjectAnalyzerService;
import com.argus.analyzer.support.SourceLocator;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

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
        // 边界校验在 adapter 完成；核心只消费不可变命令（O-11）。
        Path sourcePath = sourceLocator.resolveForAnalysis(request.sourcePath());
        AnalysisCommand command = AnalysisCommandMapper.map(request, sourcePath);
        AnalysisResult result = analyzerService.analyze(command, request.maven(),
                AnalysisProgressListener.NOOP);
        return AnalysisResultMapper.map(result);
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
        // 提交时即做 real-path 边界校验，非法路径快速失败（400），不进入作业队列。
        // 异常→HTTP 状态映射统一由 AnalysisExceptionHandler 承担（J3）。
        Path sourcePath = sourceLocator.resolveForAnalysis(request.sourcePath());
        AnalysisCommand command = AnalysisCommandMapper.map(request, sourcePath);
        return AnalysisJobStatusMapper.map(jobService.submit(command, request.maven()));
    }

    @GetMapping("/analyze/jobs/{jobId}")
    public AnalysisJobStatusResponse getJob(@PathVariable String jobId) {
        return AnalysisJobStatusMapper.map(jobService.getStatus(jobId));
    }

    /**
     * 幂等协作取消（O-04）：PENDING/RUNNING 作业请求取消，已终态则返回当前状态。
     */
    @DeleteMapping("/analyze/jobs/{jobId}")
    public AnalysisJobStatusResponse cancelJob(@PathVariable String jobId) {
        return AnalysisJobStatusMapper.map(jobService.cancel(jobId));
    }

    @GetMapping("/analyze/jobs/{jobId}/result")
    public AnalyzeResponse getJobResult(@PathVariable String jobId) {
        return AnalysisResultMapper.map(jobService.getResult(jobId));
    }
}
