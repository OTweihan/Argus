package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.service.ProjectAnalyzerService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/argus/api")
public class AnalysisController {

    private final ProjectAnalyzerService analyzerService;

    public AnalysisController(ProjectAnalyzerService analyzerService) {
        this.analyzerService = analyzerService;
    }

    @PostMapping("/analyze")
    public AnalyzeResponse analyze(@Valid @RequestBody AnalyzeRequest request) {
        return analyzerService.analyze(request);
    }
}
