package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.*;
import com.argus.analyzer.support.ProjectIndexCache;
import com.argus.analyzer.support.SourceLocator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

@Service
public class ProjectAnalyzerService {

    private static final Logger log = LoggerFactory.getLogger(ProjectAnalyzerService.class);

    private final ControllerExtractor controllerExtractor;
    private final CallGraphBuilder callGraphBuilder;
    private final FindingDetector findingDetector;
    private final ExecutionFlowTracer executionFlowTracer;
    private final CommunityClusterer communityClusterer;
    private final SourceLocator sourceLocator;
    private final ProjectIndexCache indexCache;

    public ProjectAnalyzerService(ControllerExtractor controllerExtractor,
                                  CallGraphBuilder callGraphBuilder,
                                  FindingDetector findingDetector,
                                  ExecutionFlowTracer executionFlowTracer,
                                  CommunityClusterer communityClusterer,
                                  SourceLocator sourceLocator,
                                  ProjectIndexCache indexCache) {
        this.controllerExtractor = controllerExtractor;
        this.callGraphBuilder = callGraphBuilder;
        this.findingDetector = findingDetector;
        this.executionFlowTracer = executionFlowTracer;
        this.communityClusterer = communityClusterer;
        this.sourceLocator = sourceLocator;
        this.indexCache = indexCache;
    }

    public AnalyzeResponse analyze(AnalyzeRequest request) {
        Path sourcePath = sourceLocator.resolve(request.getSourcePath());
        String canonicalPath = sourcePath.toAbsolutePath().normalize().toString();

        AnalyzeResponse cached = indexCache.get(canonicalPath);
        if (cached != null) {
            return cached;
        }

        String scope = request.getScope() != null ? request.getScope() : "all";

        // Step 1: 无依赖的独立分析，并行执行
        CompletableFuture<List<EndpointInfo>> endpointsFuture = CompletableFuture.completedFuture(List.of());
        CompletableFuture<CallGraphBuilder.BuildResult> buildResultFuture = CompletableFuture.completedFuture(null);
        CompletableFuture<List<FindingItem>> findingsFuture = CompletableFuture.completedFuture(List.of());

        boolean runEndpoints = "endpoints".equals(scope) || "all".equals(scope) || "flows".equals(scope);
        boolean runCallGraph = "callgraph".equals(scope) || "all".equals(scope)
                || "flows".equals(scope) || "clusters".equals(scope);
        boolean runFindings = "all".equals(scope);

        if (runEndpoints) {
            endpointsFuture = CompletableFuture.supplyAsync(() -> controllerExtractor.extract(sourcePath));
        }
        if (runCallGraph) {
            buildResultFuture = CompletableFuture.supplyAsync(() -> callGraphBuilder.build(sourcePath));
        }
        if (runFindings) {
            findingsFuture = CompletableFuture.supplyAsync(() -> findingDetector.detect(sourcePath));
        }

        // Step 2: 依赖 callgraph 的衍生分析
        CompletableFuture<Map<String, CallGraphNode>> callGraphFuture = buildResultFuture
                .thenApplyAsync(result -> result != null ? result.graph() : Map.of());

        CompletableFuture<AnalyzerDiagnostics> diagnosticsFuture = buildResultFuture
                .thenApplyAsync(result -> result != null ? result.diagnostics() : new AnalyzerDiagnostics());

        CompletableFuture<List<ExecutionFlow>> flowsFuture = endpointsFuture.thenCombineAsync(callGraphFuture,
                (endpoints, callGraph) -> {
                    boolean runFlows = "all".equals(scope) || "flows".equals(scope);
                    if (!runFlows || endpoints.isEmpty() || callGraph.isEmpty()) {
                        return List.<ExecutionFlow>of();
                    }
                    return executionFlowTracer.trace(callGraph, endpoints);
                });

        CompletableFuture<List<ClusterInfo>> clustersFuture = callGraphFuture.thenApplyAsync(callGraph -> {
            boolean runClusters = "all".equals(scope) || "clusters".equals(scope);
            if (!runClusters || callGraph.isEmpty()) {
                return List.<ClusterInfo>of();
            }
            return communityClusterer.cluster(callGraph);
        });

        List<EndpointInfo> endpoints = endpointsFuture.join();
        Map<String, CallGraphNode> callGraph = callGraphFuture.join();
        List<FindingItem> findings = findingsFuture.join();
        List<ExecutionFlow> flows = flowsFuture.join();
        List<ClusterInfo> clusters = clustersFuture.join();
        AnalyzerDiagnostics diagnostics = diagnosticsFuture.join();

        AnalyzeResponse response = new AnalyzeResponse(endpoints, callGraph, findings, flows, clusters, diagnostics);
        indexCache.put(canonicalPath, response);

        log.info("白盒分析完成: scope={} endpoints={} callgraph_nodes={} findings={} flows={} clusters={}",
                scope, endpoints.size(), callGraph.size(), findings.size(), flows.size(), clusters.size());
        if (diagnostics != null) {
            log.info("解析诊断: total_files={} parsed={} failed={} calls={} resolved_high={} resolved_medium={} unresolved={}",
                    diagnostics.getTotalSourceFiles(), diagnostics.getParsedFileCount(),
                    diagnostics.getFailedFileCount(), diagnostics.getTotalCalls(),
                    diagnostics.getResolvedHigh(), diagnostics.getResolvedMedium(),
                    diagnostics.getUnresolved());
        }
        return response;
    }
}
