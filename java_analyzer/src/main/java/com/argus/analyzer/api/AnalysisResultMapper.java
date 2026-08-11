package com.argus.analyzer.api;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.domain.AnalysisResult;

/**
 * 内部 {@link AnalysisResult} → HTTP wire {@link AnalyzeResponse} 映射（O-11）。
 *
 * <p>结果模型为领域共享类型，映射为纯字段拷贝；HTTP adapter 是唯一产出
 * wire DTO 的地方。</p>
 */
public final class AnalysisResultMapper {

    private AnalysisResultMapper() {}

    public static AnalyzeResponse map(AnalysisResult result) {
        if (result == null) {
            return null;
        }
        return new AnalyzeResponse(
                result.endpoints(),
                result.callGraph(),
                result.findings(),
                result.executionFlows(),
                result.clusters(),
                result.diagnostics()
        );
    }
}
