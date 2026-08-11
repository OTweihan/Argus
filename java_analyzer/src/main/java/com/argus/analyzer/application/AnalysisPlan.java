package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisPass;

import java.util.List;

/**
 * 一次分析的计划：选定的一组 AnalysisPass（O-11）。
 *
 * <p>由 {@link PlanRegistry} 根据 {@code AnalysisScope} 从已注册 pass 集合选出，
 * 顺序即 pass 注册顺序；依赖关系在运行期由 {@link PassExecutor} 拓扑展开。</p>
 */
public record AnalysisPlan(List<AnalysisPass> passes) {

    public AnalysisPlan {
        passes = passes == null ? List.of() : List.copyOf(passes);
    }
}
