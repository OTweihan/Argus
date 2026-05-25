package com.argus.analyzer.api.dto;

import java.util.List;
import java.util.Map;

public class AnalyzeResponse {

    private List<EndpointInfo> endpoints;
    private Map<String, CallGraphNode> callGraph;
    private List<FindingItem> findings;
    private List<ExecutionFlow> executionFlows;
    private List<ClusterInfo> clusters;
    private AnalyzerDiagnostics diagnostics;

    public AnalyzeResponse() {}

    public AnalyzeResponse(List<EndpointInfo> endpoints, Map<String, CallGraphNode> callGraph,
                           List<FindingItem> findings, List<ExecutionFlow> executionFlows,
                           List<ClusterInfo> clusters, AnalyzerDiagnostics diagnostics) {
        this.endpoints = endpoints;
        this.callGraph = callGraph;
        this.findings = findings;
        this.executionFlows = executionFlows;
        this.clusters = clusters;
        this.diagnostics = diagnostics;
    }

    public List<EndpointInfo> getEndpoints() { return endpoints; }
    public void setEndpoints(List<EndpointInfo> endpoints) { this.endpoints = endpoints; }

    public Map<String, CallGraphNode> getCallGraph() { return callGraph; }
    public void setCallGraph(Map<String, CallGraphNode> callGraph) { this.callGraph = callGraph; }

    public List<FindingItem> getFindings() { return findings; }
    public void setFindings(List<FindingItem> findings) { this.findings = findings; }

    public List<ExecutionFlow> getExecutionFlows() { return executionFlows; }
    public void setExecutionFlows(List<ExecutionFlow> executionFlows) { this.executionFlows = executionFlows; }

    public List<ClusterInfo> getClusters() { return clusters; }
    public void setClusters(List<ClusterInfo> clusters) { this.clusters = clusters; }

    public AnalyzerDiagnostics getDiagnostics() { return diagnostics; }
    public void setDiagnostics(AnalyzerDiagnostics diagnostics) { this.diagnostics = diagnostics; }
}
