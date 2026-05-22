package com.argus.analyzer.api.dto;

import java.util.List;
import java.util.Map;

public class AnalyzeResponse {

    private List<EndpointInfo> endpoints;
    private Map<String, CallGraphNode> callGraph;
    private List<FindingItem> findings;

    public AnalyzeResponse() {}

    public AnalyzeResponse(List<EndpointInfo> endpoints, Map<String, CallGraphNode> callGraph, List<FindingItem> findings) {
        this.endpoints = endpoints;
        this.callGraph = callGraph;
        this.findings = findings;
    }

    public List<EndpointInfo> getEndpoints() { return endpoints; }
    public void setEndpoints(List<EndpointInfo> endpoints) { this.endpoints = endpoints; }

    public Map<String, CallGraphNode> getCallGraph() { return callGraph; }
    public void setCallGraph(Map<String, CallGraphNode> callGraph) { this.callGraph = callGraph; }

    public List<FindingItem> getFindings() { return findings; }
    public void setFindings(List<FindingItem> findings) { this.findings = findings; }
}
