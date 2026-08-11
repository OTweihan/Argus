package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeRequest;
import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisScope;

import java.nio.file.Path;
import java.util.List;

/**
 * HTTP wire 请求 → 内部不可变 {@link AnalysisCommand} 映射（O-11）。
 *
 * <p>{@code sourcePath} 必须已通过 real-path/allowed-roots 边界校验
 * （{@link SourceLocator#resolveForAnalysis}），命令携带即已校验路径。</p>
 */
public final class AnalysisCommandMapper {

    private AnalysisCommandMapper() {}

    public static AnalysisCommand map(AnalyzeRequest request, Path resolvedSourcePath) {
        return new AnalysisCommand(
                resolvedSourcePath,
                AnalysisScope.from(request.scope()),
                request.targetModules() == null ? List.of() : List.copyOf(request.targetModules()),
                request.clientRequestId(),
                request.timeoutSeconds(),
                request.sourceRevision(),
                request.snapshotDigest()
        );
    }
}
