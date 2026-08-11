package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisScope;
import com.argus.analyzer.domain.Capability;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class PlanRegistryTest {

    private static final PlanRegistry REGISTRY = PlanRegistry.of(List.of(
            pass("endpoints", Capability.ENDPOINTS),
            pass("callgraph", Capability.CALL_GRAPH),
            pass("findings", Capability.FINDINGS),
            pass("flows", Capability.FLOWS, Capability.CALL_GRAPH, Capability.ENDPOINTS),
            pass("clusters", Capability.CLUSTERS, Capability.CALL_GRAPH)));

    private static AnalysisPass pass(String id, Capability produced, Capability... requires) {
        return new AnalysisPass() {
            @Override public String id() { return id; }
            @Override public Capability produced() { return produced; }
            @Override public Set<Capability> requires() { return Set.of(requires); }
            @Override public boolean required() { return true; }
            @Override public AnalysisContribution run(AnalysisContext context) {
                return new AnalysisContribution(produced, List.of());
            }
        };
    }

    @Test
    void allScopeSelectsAllPasses() {
        var plan = REGISTRY.planFor(AnalysisScope.ALL);
        assertThat(plan.passes()).extracting(AnalysisPass::id).containsExactlyInAnyOrder(
                "endpoints", "callgraph", "findings", "flows", "clusters");
    }

    @Test
    void endpointsScopeSelectsOnlyEndpoints() {
        var plan = REGISTRY.planFor(AnalysisScope.ENDPOINTS);
        assertThat(plan.passes()).extracting(AnalysisPass::id).containsExactly("endpoints");
    }

    @Test
    void flowsScopeSelectsDependencyClosure() {
        var plan = REGISTRY.planFor(AnalysisScope.FLOWS);
        assertThat(plan.passes()).extracting(AnalysisPass::id).containsExactlyInAnyOrder(
                "endpoints", "callgraph", "flows");
    }

    @Test
    void clustersScopeSelectsCallGraphAndClusters() {
        var plan = REGISTRY.planFor(AnalysisScope.CLUSTERS);
        assertThat(plan.passes()).extracting(AnalysisPass::id).containsExactlyInAnyOrder(
                "callgraph", "clusters");
    }

    @Test
    void modulesScopeSelectsNothing() {
        var plan = REGISTRY.planFor(AnalysisScope.MODULES);
        assertThat(plan.passes()).isEmpty();
    }

    @Test
    void planPassesAreImmutableCopy() {
        var plan = REGISTRY.planFor(AnalysisScope.ALL);
        assertThat(plan.passes()).isNotSameAs(REGISTRY.planFor(AnalysisScope.ALL).passes());
    }
}
