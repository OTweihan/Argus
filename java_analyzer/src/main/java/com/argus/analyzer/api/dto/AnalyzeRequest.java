package com.argus.analyzer.api.dto;

import jakarta.validation.constraints.NotBlank;

public class AnalyzeRequest {

    @NotBlank(message = "sourcePath is required")
    private String sourcePath;

    private String scope = "all";

    public AnalyzeRequest() {}

    public AnalyzeRequest(String sourcePath, String scope) {
        this.sourcePath = sourcePath;
        this.scope = scope;
    }

    public String getSourcePath() { return sourcePath; }
    public void setSourcePath(String sourcePath) { this.sourcePath = sourcePath; }

    public String getScope() { return scope; }
    public void setScope(String scope) { this.scope = scope; }
}
