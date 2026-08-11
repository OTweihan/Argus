package com.argus.analyzer.support;

import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.model.CallEdge;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.ClusterInfo;
import com.argus.analyzer.domain.model.Confidence;
import com.argus.analyzer.domain.model.FindingItem;
import com.argus.analyzer.domain.model.ResolutionType;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ResponseWeightEstimatorTest {

    @Test
    void shouldReturnZeroForNull() {
        assertThat(ResponseWeightEstimator.estimateWeight(null)).isZero();
    }

    @Test
    void shouldEstimateSmallFixedOverheadForEmptyResponse() {
        AnalysisResult empty = new AnalysisResult(
                List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        assertThat(ResponseWeightEstimator.estimateWeight(empty)).isEqualTo(64L);
    }

    @Test
    void shouldTolerateNullCollections() {
        AnalysisResult response = new AnalysisResult(null, null, null, null, null, null);
        assertThat(ResponseWeightEstimator.estimateWeight(response)).isEqualTo(64L);
    }

    @Test
    void shouldWeighMoreWithMoreNodesAndEdges() {
        long oneNode = ResponseWeightEstimator.estimateWeight(responseWith(1, 1));
        long fiveNodes = ResponseWeightEstimator.estimateWeight(responseWith(5, 1));
        long fiveByFive = ResponseWeightEstimator.estimateWeight(responseWith(5, 5));

        assertThat(fiveNodes).isGreaterThan(oneNode);
        assertThat(fiveByFive).isGreaterThan(fiveNodes);
    }

    @Test
    void shouldWeighStringContentAsApproximateUtf16Bytes() {
        long tiny = ResponseWeightEstimator.estimateWeight(findingsResponse("x"));
        long large = ResponseWeightEstimator.estimateWeight(findingsResponse("x".repeat(1_000_000)));

        assertThat(large).isGreaterThan(tiny);
        // 字符串按 UTF-16 估算：100 万字符 ≈ 200 万字节 + 开销。
        assertThat(large).isGreaterThan(2_000_000L);
    }

    @Test
    void shouldWeighFindingsAndClusters() {
        long findings = ResponseWeightEstimator.estimateWeight(findingsResponse("a", "b", "c"));
        long clusters = ResponseWeightEstimator.estimateWeight(clustersResponse(3));
        long empty = ResponseWeightEstimator.estimateWeight(new AnalysisResult(
                List.of(), Map.of(), List.of(), List.of(), List.of(), null));

        assertThat(findings).isGreaterThan(empty);
        assertThat(clusters).isGreaterThan(empty);
    }

    private static AnalysisResult responseWith(int nodes, int edges) {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        for (int i = 0; i < nodes; i++) {
            List<CallEdge> callees = new ArrayList<>();
            for (int j = 0; j < edges; j++) {
                callees.add(new CallEdge(
                        "com.acme.Thing" + i + "#call" + j,
                        "call" + j,
                        "Thing" + i,
                        ResolutionType.SYMBOL_SOLVER,
                        Confidence.HIGH,
                        List.of("com.acme.Thing" + i),
                        "Thing" + i + ".java",
                        i + j));
            }
            graph.put("com.acme.Thing" + i + "#run()",
                    new CallGraphNode("com.acme.Thing" + i, "run", "()V", callees));
        }
        return new AnalysisResult(List.of(), graph, List.of(), List.of(), List.of(), null);
    }

    private static AnalysisResult findingsResponse(String... titles) {
        List<FindingItem> findings = new ArrayList<>();
        for (String title : titles) {
            findings.add(new FindingItem(
                    "rule1", "HIGH", title, "desc", "a.java", 1, "snippet", "cat", "HIGH"));
        }
        return new AnalysisResult(List.of(), Map.of(), findings, List.of(), List.of(), null);
    }

    private static AnalysisResult clustersResponse(int count) {
        List<ClusterInfo> clusters = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            clusters.add(new ClusterInfo(
                    "cluster_" + i, "label" + i, List.of("a.Thing" + i + "#m()")));
        }
        return new AnalysisResult(List.of(), Map.of(), List.of(), List.of(), clusters, null);
    }
}
