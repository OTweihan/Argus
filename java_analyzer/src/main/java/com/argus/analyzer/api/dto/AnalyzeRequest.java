package com.argus.analyzer.api.dto;

import com.argus.analyzer.env.MavenConfig;
import jakarta.validation.constraints.NotBlank;

import java.util.List;

public record AnalyzeRequest(
    @NotBlank(message = "sourcePath is required") String sourcePath,
    String scope,
    List<String> targetModules,
    MavenConfig maven,
    String clientRequestId
) {
    public AnalyzeRequest {
        if (scope == null) scope = "all";
    }

    public AnalyzeRequest(String sourcePath, String scope) {
        this(sourcePath, scope, null, null, null);
    }

    public AnalyzeRequest(String sourcePath, String scope, List<String> targetModules, MavenConfig maven) {
        this(sourcePath, scope, targetModules, maven, null);
    }
}
