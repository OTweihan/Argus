package com.argus.analyzer.api.dto;

import com.argus.analyzer.env.MavenConfig;
import jakarta.validation.constraints.NotBlank;

import java.util.List;

/**
 * 分析请求（Python→Java wire contract）。
 *
 * <p>{@code sourceRevision} / {@code snapshotDigest} 为 O-07 兼容新增字段：
 * Python 在物化不可变快照时计算一次并传入，Java 缓存键据此免去每次查找时
 * 全量读取源码树。旧客户端不传时回退到现有全量哈希指纹。</p>
 */
public record AnalyzeRequest(
    @NotBlank(message = "sourcePath is required") String sourcePath,
    String scope,
    List<String> targetModules,
    MavenConfig maven,
    String clientRequestId,
    Long timeoutSeconds,
    String sourceRevision,
    String snapshotDigest
) {
    public AnalyzeRequest {
        if (scope == null) scope = "all";
    }

    public AnalyzeRequest(String sourcePath, String scope) {
        this(sourcePath, scope, null, null, null, null, null, null);
    }

    public AnalyzeRequest(String sourcePath, String scope, List<String> targetModules, MavenConfig maven) {
        this(sourcePath, scope, targetModules, maven, null, null, null, null);
    }

    public AnalyzeRequest(String sourcePath, String scope, List<String> targetModules, MavenConfig maven,
                          String clientRequestId) {
        this(sourcePath, scope, targetModules, maven, clientRequestId, null, null, null);
    }

    public AnalyzeRequest(String sourcePath, String scope, List<String> targetModules, MavenConfig maven,
                          String clientRequestId, Long timeoutSeconds) {
        this(sourcePath, scope, targetModules, maven, clientRequestId, timeoutSeconds, null, null);
    }
}
