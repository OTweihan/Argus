package com.argus.analyzer.api.dto;

import java.util.List;
import java.util.Map;

public record AnalyzeResponse(
    List<EndpointInfo> endpoints,
    Map<String, CallGraphNode> callGraph,
    List<FindingItem> findings,
    List<ExecutionFlow> executionFlows,
    List<ClusterInfo> clusters,
    AnalyzerDiagnostics diagnostics
) {}
