package com.argus.analyzer.domain;

import java.nio.file.Path;
import java.util.List;

/**
 * 一次分析的不可变命令（O-11）。
 *
 * <p>由 HTTP adapter 从 wire DTO 映射而来，携带已通过 real-path 边界校验的
 * {@code sourcePath}；核心流程只消费本命令与 {@code AnalysisResult}，不读取
 * HTTP DTO。Maven 配置不属于领域模型，作为独立参数在应用层传递。</p>
 */
public record AnalysisCommand(
        Path sourcePath,
        AnalysisScope scope,
        List<String> targetModules,
        String clientRequestId,
        Long timeoutSeconds,
        String sourceRevision,
        String snapshotDigest
) {
    public AnalysisCommand {
        sourcePath = sourcePath.toAbsolutePath().normalize();
        scope = scope == null ? AnalysisScope.ALL : scope;
        targetModules = targetModules == null ? List.of() : List.copyOf(targetModules);
    }
}
