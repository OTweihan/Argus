package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.Capability;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * AnalysisPass 能力图校验（O-11）。
 *
 * <p>在启动装配时校验全部已注册 pass：重复产出、缺失依赖（某 pass 需要的
 * 能力没有生产者）、以及能力依赖环。能力依赖必须构成无环图。</p>
 */
public final class PlanValidator {

    private PlanValidator() {}

    /**
     * 校验已注册 pass 集合。
     *
     * @throws IllegalArgumentException 重复能力 / 缺失依赖 / 依赖环
     */
    public static void validate(List<AnalysisPass> passes) {
        // 1) 重复产出能力
        Map<Capability, AnalysisPass> producer = new HashMap<>();
        for (AnalysisPass pass : passes) {
            AnalysisPass previous = producer.put(pass.produced(), pass);
            if (previous != null) {
                throw new IllegalArgumentException(
                        "Duplicate capability '" + pass.produced() + "' produced by passes '"
                                + previous.id() + "' and '" + pass.id() + "'");
            }
        }
        // 2) 缺失依赖：每个 requires 能力必须由某个已注册 pass 产出
        for (AnalysisPass pass : passes) {
            for (Capability required : pass.requires()) {
                if (!producer.containsKey(required)) {
                    throw new IllegalArgumentException(
                            "Pass '" + pass.id() + "' requires capability '" + required
                                    + "' which no registered pass produces");
                }
            }
        }
        // 3) 能力依赖环：DFS over passes
        Set<AnalysisPass> visiting = new HashSet<>();
        Set<AnalysisPass> done = new HashSet<>();
        for (AnalysisPass pass : passes) {
            dfs(pass, producer, visiting, done);
        }
    }

    private static void dfs(AnalysisPass pass, Map<Capability, AnalysisPass> producer,
                            Set<AnalysisPass> visiting, Set<AnalysisPass> done) {
        if (done.contains(pass)) {
            return;
        }
        if (visiting.contains(pass)) {
            throw new IllegalArgumentException(
                    "Capability dependency cycle involving pass '" + pass.id() + "'");
        }
        visiting.add(pass);
        for (Capability required : pass.requires()) {
            AnalysisPass dependency = producer.get(required);
            if (dependency != null) {
                dfs(dependency, producer, visiting, done);
            }
        }
        visiting.remove(pass);
        done.add(pass);
    }
}
