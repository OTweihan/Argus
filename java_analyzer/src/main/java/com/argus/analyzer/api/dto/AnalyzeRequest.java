package com.argus.analyzer.api.dto;

import com.argus.analyzer.env.MavenConfig;
import jakarta.validation.constraints.NotBlank;

import java.util.List;

public class AnalyzeRequest {

    @NotBlank(message = "sourcePath is required")
    private String sourcePath;

    private String scope = "all";

    private List<String> targetModules;

    private MavenConfig maven;

    public AnalyzeRequest() {}

    public AnalyzeRequest(String sourcePath, String scope) {
        this.sourcePath = sourcePath;
        this.scope = scope;
    }

    public String getSourcePath() { return sourcePath; }
    public void setSourcePath(String sourcePath) { this.sourcePath = sourcePath; }

    public String getScope() { return scope; }
    public void setScope(String scope) { this.scope = scope; }

    public List<String> getTargetModules() { return targetModules; }
    public void setTargetModules(List<String> targetModules) { this.targetModules = targetModules; }

    public MavenConfig getMaven() { return maven; }
    public void setMaven(MavenConfig maven) { this.maven = maven; }
}
