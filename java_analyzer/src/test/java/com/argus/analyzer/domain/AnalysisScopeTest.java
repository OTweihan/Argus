package com.argus.analyzer.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AnalysisScopeTest {

    @Test
    void nullMapsToAll() {
        assertThat(AnalysisScope.from(null)).isEqualTo(AnalysisScope.ALL);
    }

    @Test
    void knownValuesMapExactly() {
        assertThat(AnalysisScope.from("all")).isEqualTo(AnalysisScope.ALL);
        assertThat(AnalysisScope.from("endpoints")).isEqualTo(AnalysisScope.ENDPOINTS);
        assertThat(AnalysisScope.from("callgraph")).isEqualTo(AnalysisScope.CALLGRAPH);
        assertThat(AnalysisScope.from("flows")).isEqualTo(AnalysisScope.FLOWS);
        assertThat(AnalysisScope.from("clusters")).isEqualTo(AnalysisScope.CLUSTERS);
        assertThat(AnalysisScope.from("modules")).isEqualTo(AnalysisScope.MODULES);
        assertThat(AnalysisScope.from("changed")).isEqualTo(AnalysisScope.CHANGED);
    }

    @Test
    void unknownOrCaseMismatchFallsBackToModulesOnly() {
        // 旧行为：未知/大小写不匹配的 scope 不运行任何分析 pass（保守回退 modules）。
        assertThat(AnalysisScope.from("All")).isEqualTo(AnalysisScope.MODULES);
        assertThat(AnalysisScope.from("bogus")).isEqualTo(AnalysisScope.MODULES);
        assertThat(AnalysisScope.from("")).isEqualTo(AnalysisScope.MODULES);
        assertThat(AnalysisScope.from("findings")).isEqualTo(AnalysisScope.MODULES);
    }

    @Test
    void allEnablesEveryCapability() {
        assertThat(AnalysisScope.ALL.enabledCapabilities()).containsExactlyInAnyOrder(
                Capability.ENDPOINTS, Capability.CALL_GRAPH, Capability.FINDINGS,
                Capability.FLOWS, Capability.CLUSTERS);
    }

    @Test
    void flowsEnablesEndpointsCallGraphAndFlows() {
        assertThat(AnalysisScope.FLOWS.enabledCapabilities()).containsExactlyInAnyOrder(
                Capability.ENDPOINTS, Capability.CALL_GRAPH, Capability.FLOWS);
    }

    @Test
    void clustersEnablesCallGraphAndClustersOnly() {
        assertThat(AnalysisScope.CLUSTERS.enabledCapabilities()).containsExactlyInAnyOrder(
                Capability.CALL_GRAPH, Capability.CLUSTERS);
    }

    @Test
    void modulesAndChangedEnableNothing() {
        assertThat(AnalysisScope.MODULES.enabledCapabilities()).isEmpty();
        assertThat(AnalysisScope.CHANGED.enabledCapabilities()).isEmpty();
    }

    @Test
    void commandDefaultsScopeToAllAndNormalizesPath() {
        var command = new AnalysisCommand(
                java.nio.file.Path.of("/tmp/x/"), null, null, null, null, null, null);
        assertThat(command.scope()).isEqualTo(AnalysisScope.ALL);
        assertThat(command.targetModules()).isEmpty();
        assertThat(command.sourcePath().isAbsolute()).isTrue();
    }
}
