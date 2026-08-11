package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.Capability;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanValidatorTest {

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
    void acceptsAcyclicPassSet() {
        List<AnalysisPass> passes = List.of(
                pass("leaf-a", Capability.ENDPOINTS),
                pass("leaf-b", Capability.CALL_GRAPH),
                pass("derived", Capability.FLOWS, Capability.CALL_GRAPH, Capability.ENDPOINTS));
        PlanValidator.validate(passes); // 不抛
    }

    @Test
    void rejectsDuplicateProducedCapability() {
        List<AnalysisPass> passes = List.of(
                pass("a", Capability.ENDPOINTS),
                pass("b", Capability.ENDPOINTS));
        assertThatThrownBy(() -> PlanValidator.validate(passes))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Duplicate capability")
                .hasMessageContaining("ENDPOINTS")
                .hasMessageContaining("a")
                .hasMessageContaining("b");
    }

    @Test
    void rejectsMissingDependency() {
        List<AnalysisPass> passes = List.of(
                pass("flows", Capability.FLOWS, Capability.CALL_GRAPH));
        assertThatThrownBy(() -> PlanValidator.validate(passes))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("requires capability 'CALL_GRAPH'");
    }

    @Test
    void rejectsDependencyCycle() {
        // flows → (produces CALL_GRAPH→) callgraph → (produces FLOWS→) flows 直接成环
        List<AnalysisPass> passes = List.of(
                pass("cycle-a", Capability.CALL_GRAPH, Capability.FLOWS),
                pass("cycle-b", Capability.FLOWS, Capability.CALL_GRAPH));
        assertThatThrownBy(() -> PlanValidator.validate(passes))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("cycle");
    }

    @Test
    void rejectsTransitiveCycle() {
        List<AnalysisPass> passes = List.of(
                pass("a", Capability.ENDPOINTS, Capability.CLUSTERS),
                pass("b", Capability.CALL_GRAPH, Capability.ENDPOINTS),
                pass("c", Capability.CLUSTERS, Capability.CALL_GRAPH));
        assertThatThrownBy(() -> PlanValidator.validate(passes))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("cycle");
    }
}
