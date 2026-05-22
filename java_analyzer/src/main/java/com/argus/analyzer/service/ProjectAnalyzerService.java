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
    private final SourceLocator sourceLocator;
    private final ProjectIndexCache indexCache;

    public ProjectAnalyzerService(ControllerExtractor controllerExtractor,
                                  CallGraphBuilder callGraphBuilder,
                                  FindingDetector findingDetector,
                                  SourceLocator sourceLocator,
                                  ProjectIndexCache indexCache) {
        this.controllerExtractor = controllerExtractor;
        this.callGraphBuilder = callGraphBuilder;
        this.findingDetector = findingDetector;
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

        // 三步分析无数据依赖，并行执行以缩短总耗时
        CompletableFuture<List<EndpointInfo>> endpointsFuture = CompletableFuture.completedFuture(List.of());
        CompletableFuture<Map<String, CallGraphNode>> callGraphFuture = CompletableFuture.completedFuture(Map.of());
        CompletableFuture<List<FindingItem>> findingsFuture = CompletableFuture.completedFuture(List.of());

        if ("endpoints".equals(scope) || "all".equals(scope)) {
            endpointsFuture = CompletableFuture.supplyAsync(() -> controllerExtractor.extract(sourcePath));
        }
        if ("callgraph".equals(scope) || "all".equals(scope)) {
            callGraphFuture = CompletableFuture.supplyAsync(() -> callGraphBuilder.build(sourcePath));
        }
        if ("all".equals(scope)) {
            findingsFuture = CompletableFuture.supplyAsync(() -> findingDetector.detect(sourcePath));
        }

        List<EndpointInfo> endpoints = endpointsFuture.join();
        Map<String, CallGraphNode> callGraph = callGraphFuture.join();
        List<FindingItem> findings = findingsFuture.join();

        AnalyzeResponse response = new AnalyzeResponse(endpoints, callGraph, findings);
        indexCache.put(canonicalPath, response);
        log.info("白盒分析完成: scope={} endpoints={} callgraph_nodes={} findings={}",
                scope, endpoints.size(), callGraph.size(), findings.size());
        return response;
    }
}
