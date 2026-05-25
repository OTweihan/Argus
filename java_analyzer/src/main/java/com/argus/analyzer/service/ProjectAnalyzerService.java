package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.*;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenClasspathResolver;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModule;
import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.ModuleClassifier;
import com.argus.analyzer.support.ProjectIndexCache;
import com.argus.analyzer.support.SourceFileScanner;
import com.argus.analyzer.support.SourceLocator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

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
    private final MavenClasspathResolver classpathResolver;
    private final SourceFileScanner sourceFileScanner;
    private final ModuleClassifier moduleClassifier;

    public ProjectAnalyzerService(ControllerExtractor controllerExtractor,
                                  CallGraphBuilder callGraphBuilder,
                                  FindingDetector findingDetector,
                                  ExecutionFlowTracer executionFlowTracer,
                                  CommunityClusterer communityClusterer,
                                  SourceLocator sourceLocator,
                                  ProjectIndexCache indexCache,
                                  MavenClasspathResolver classpathResolver,
                                  SourceFileScanner sourceFileScanner,
                                  ModuleClassifier moduleClassifier) {
        this.controllerExtractor = controllerExtractor;
        this.callGraphBuilder = callGraphBuilder;
        this.findingDetector = findingDetector;
        this.executionFlowTracer = executionFlowTracer;
        this.communityClusterer = communityClusterer;
        this.sourceLocator = sourceLocator;
        this.indexCache = indexCache;
        this.classpathResolver = classpathResolver;
        this.sourceFileScanner = sourceFileScanner;
        this.moduleClassifier = moduleClassifier;
    }

    public AnalyzeResponse analyze(AnalyzeRequest request) {
        return analyze(request, AnalysisProgressListener.NOOP);
    }

    public AnalyzeResponse analyze(AnalyzeRequest request, AnalysisProgressListener progress) {
        Path sourcePath = sourceLocator.resolve(request.getSourcePath());
        String canonicalPath = sourcePath.toAbsolutePath().normalize().toString();

        AnalyzeResponse cached = indexCache.get(canonicalPath);
        if (cached != null) {
            progress.onEvent("cache", "INFO", "Analysis result loaded from cache");
            return cached;
        }

        String scope = request.getScope() != null ? request.getScope() : "all";
        MavenConfig mavenConfig = request.getMaven() != null ? request.getMaven() : new MavenConfig();

        // P0: 构建 Maven 模块索引（触发 POM 扫描）
        MavenModuleIndex moduleIndex = sourceFileScanner.getCurrentModuleIndex(sourcePath);
        if (moduleIndex != null) {
            log.info("[POM] Module index built: {} modules, rootPom={}",
                    moduleIndex.getModuleCount(), moduleIndex.getRootPom());
        } else {
            log.info("[POM] No Maven module index (non-Maven project or scan failed)");
        }

        // P2: 模块分类 + 自动选择目标模块（用户未指定 targetModules 时）
        List<String> targetModules = request.getTargetModules();
        if ((targetModules == null || targetModules.isEmpty()) && moduleIndex != null) {
            log.info("[AUTO_DETECT] No target modules specified, running classification...");
            moduleClassifier.classifyAll(moduleIndex);
            List<MavenModule> targets = moduleClassifier.selectTargets(moduleIndex);
            targetModules = targets.stream()
                    .map(MavenModule::getDisplayName)
                    .toList();
            log.info("[AUTO_DETECT] Selected {} target modules: {}", targetModules.size(), targetModules);
        }

        // P1: 模块感知的 classpath 解析
        ClasspathResult cpResult;
        if (moduleIndex != null && targetModules != null && !targetModules.isEmpty()) {
            log.info("[CLASSPATH] Using module-aware resolution for {} modules: {}",
                    targetModules.size(), targetModules);
            cpResult = classpathResolver.resolve(moduleIndex, targetModules, mavenConfig, progress);
        } else {
            log.info("[CLASSPATH] Using legacy resolution (moduleIndex={}, targetModules={})",
                    moduleIndex != null, targetModules != null ? targetModules.size() : 0);
            cpResult = classpathResolver.resolve(sourcePath, mavenConfig, progress);
        }

        List<Path> classpathJars = cpResult.isAvailable()
                ? cpResult.getJars().stream().map(Path::of).toList()
                : List.of();

        log.info("Classpath: available={} source={} jars={}",
                cpResult.isAvailable(), cpResult.getSource(), cpResult.getJars().size());

        // Capture for lambda use
        final MavenModuleIndex capturedIndex = moduleIndex;
        final List<String> capturedTargetModules = targetModules;

        // Step 1: 无依赖的独立分析，并行执行
        CompletableFuture<List<EndpointInfo>> endpointsFuture = CompletableFuture.completedFuture(List.of());
        CompletableFuture<CallGraphBuilder.BuildResult> buildResultFuture = CompletableFuture.completedFuture(null);
        CompletableFuture<List<FindingItem>> findingsFuture = CompletableFuture.completedFuture(List.of());

        boolean runEndpoints = "endpoints".equals(scope) || "all".equals(scope) || "flows".equals(scope);
        boolean runCallGraph = "callgraph".equals(scope) || "all".equals(scope)
                || "flows".equals(scope) || "clusters".equals(scope);
        boolean runFindings = "all".equals(scope);

        if (runEndpoints) {
            List<Path> cp = classpathJars;
            endpointsFuture = CompletableFuture.supplyAsync(() -> controllerExtractor.extract(sourcePath, cp));
        }
        if (runCallGraph) {
            List<Path> cp = classpathJars;
            buildResultFuture = CompletableFuture.supplyAsync(() -> callGraphBuilder.build(sourcePath, cp));
        }
        if (runFindings) {
            List<Path> cp = classpathJars;
            findingsFuture = CompletableFuture.supplyAsync(() -> findingDetector.detect(sourcePath, cp));
        }

        // Step 2: 依赖 callgraph 的衍生分析
        CompletableFuture<Map<String, CallGraphNode>> callGraphFuture = buildResultFuture
                .thenApplyAsync(result -> result != null ? result.graph() : Map.of());

        CompletableFuture<AnalyzerDiagnostics> diagnosticsFuture = buildResultFuture
                .thenApplyAsync(result -> {
                    AnalyzerDiagnostics diag = result != null ? result.diagnostics() : new AnalyzerDiagnostics();
                    if (diag != null) {
                        diag.setClasspathAvailable(cpResult.isAvailable());
                        diag.setJarCount(cpResult.getJars().size());
                        diag.setClasspathSource(cpResult.getSource());
                        diag.setClasspathWarnings(cpResult.getWarnings());
                        diag.setClasspathErrors(cpResult.getErrors());
                        diag.setClasspathCommand(cpResult.getCommand());
                        diag.setClasspathExitCode(cpResult.getExitCode());
                        diag.setClasspathDurationMs(cpResult.getDurationMs());
                        diag.setClasspathStdoutTail(cpResult.getStdoutTail());
                        diag.setClasspathStderrTail(cpResult.getStderrTail());
                        diag.setClasspathTimedOut(cpResult.isTimedOut());

                        // P3: 填充模块信息
                        if (capturedIndex != null) {
                            diag.setRootPom(capturedIndex.getRootPom() != null
                                    ? capturedIndex.getRootPom().toString() : null);
                            diag.setModuleCount(capturedIndex.getModuleCount());
                            diag.setSourceRootCount(capturedIndex.getAllSourceRoots().size());
                            diag.setModules(capturedIndex.getModules().stream()
                                    .map(m -> m.getDisplayName())
                                    .collect(Collectors.toList()));

                            // P4: 模块分类摘要
                            diag.setApplicationModuleCount(capturedIndex.getApplicationModuleCount());
                            diag.setBusinessModuleCount(capturedIndex.getBusinessModuleCount());
                            diag.setLibraryModuleCount(capturedIndex.getLibraryModuleCount());
                            diag.setBomModuleCount(capturedIndex.getBomModuleCount());
                            diag.setModuleTypes(capturedIndex.getModules().stream()
                                    .filter(m -> !m.isAggregator())
                                    .collect(Collectors.toMap(
                                            MavenModule::getDisplayName,
                                            m -> m.getModuleType().name())));
                        }
                        if (capturedTargetModules != null) {
                            diag.setClasspathTargetModules(capturedTargetModules);
                        }
                    }
                    return diag;
                });

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
            log.info("解析诊断: files={}/{} calls={} H={} M={} U={} cp={} jars={}",
                    diagnostics.getParsedFileCount(), diagnostics.getTotalSourceFiles(),
                    diagnostics.getTotalCalls(), diagnostics.getResolvedHigh(),
                    diagnostics.getResolvedMedium(), diagnostics.getUnresolved(),
                    diagnostics.getClasspathSource(), diagnostics.getJarCount());
        }
        return response;
    }
}
