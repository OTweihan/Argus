package com.argus.analyzer.domain;

/**
 * 分析能力（AnalysisPass 输入/输出契约，O-11）。
 *
 * <p>每个 {@link AnalysisPass} 声明产出一种能力、消费若干能力；能力依赖构成
 * 无环图，由 {@code application.PlanValidator} 在启动时校验重复、缺失与循环。
 * 无依赖 pass 才能并行执行。</p>
 */
public enum Capability {
    ENDPOINTS,
    CALL_GRAPH,
    FINDINGS,
    FLOWS,
    CLUSTERS
}
