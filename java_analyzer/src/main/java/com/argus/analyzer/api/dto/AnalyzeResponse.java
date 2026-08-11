package com.argus.analyzer.api.dto;

import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.ClusterInfo;
import com.argus.analyzer.domain.model.EndpointInfo;
import com.argus.analyzer.domain.model.ExecutionFlow;
import com.argus.analyzer.domain.model.FindingItem;

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
