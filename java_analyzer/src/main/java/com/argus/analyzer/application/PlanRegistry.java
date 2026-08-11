package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisScope;
import com.argus.analyzer.domain.Capability;

import java.util.List;
import java.util.Set;

/**
 * 分析计划装配（O-11）。
 *
 * <p>持有全部已注册 pass（构造时经 {@link PlanValidator} 校验），并按
 * {@link AnalysisScope} 的能力集合选出单次分析的计划。实例不可变、线程安全。</p>
 */
public final class PlanRegistry {

    private final List<AnalysisPass> allPasses;

    private PlanRegistry(List<AnalysisPass> passes) {
        PlanValidator.validate(passes);
        this.allPasses = List.copyOf(passes);
    }

    public static PlanRegistry of(List<AnalysisPass> passes) {
        return new PlanRegistry(passes);
    }

    /** 按 scope 能力集合选择 pass；未启用能力的 pass 不参与本次分析。 */
    public AnalysisPlan planFor(AnalysisScope scope) {
        Set<Capability> enabled = scope.enabledCapabilities();
        List<AnalysisPass> selected = allPasses.stream()
                .filter(pass -> enabled.contains(pass.produced()))
                .toList();
        return new AnalysisPlan(selected);
    }
}
