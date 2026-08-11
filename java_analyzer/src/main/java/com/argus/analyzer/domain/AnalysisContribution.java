package com.argus.analyzer.domain;

import com.argus.analyzer.domain.model.AnalyzerDiagnostics;

/**
 * 单个 {@link AnalysisPass} 的产出贡献（O-11）。
 *
 * <p>{@code value} 是该 pass 产出的不可变结果（如调用图 {@code Map}、
 * 端点 {@code List}）；{@code diagnostics} 为该 pass 附加的解析诊断（目前仅
 * call graph pass 提供），供编排层合并进最终 {@link AnalyzerDiagnostics}。</p>
 */
public record AnalysisContribution(
        Capability capability,
        Object value,
        AnalyzerDiagnostics diagnostics
) {
    public AnalysisContribution(Capability capability, Object value) {
        this(capability, value, null);
    }
}
