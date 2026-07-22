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
import org.springframework.beans.factory.annotation.Qualifier;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
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
    private final Executor analysisWorkerExecutor;

    public ProjectAnalyzerService(ControllerExtractor controllerExtractor,
                                  CallGraphBuilder callGraphBuilder,
                                  FindingDetector findingDetector,
                                  ExecutionFlowTracer executionFlowTracer,
                                  CommunityClusterer communityClusterer,
                                  SourceLocator sourceLocator,
                                  ProjectIndexCache indexCache,
                                  MavenClasspathResolver classpathResolver,
                                  SourceFileScanner sourceFileScanner,
                                  ModuleClassifier moduleClassifier,
                                  @Qualifier("analysisWorkerExecutor") Executor analysisWorkerExecutor) {
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
        this.analysisWorkerExecutor = analysisWorkerExecutor;
    }

    public AnalyzeResponse analyze(AnalyzeRequest request) {
        return analyze(request, AnalysisProgressListener.NOOP);
    }

    public AnalyzeResponse analyze(AnalyzeRequest request, AnalysisProgressListener progress) {
        Path sourcePath = sourceLocator.resolve(request.sourcePath());
        String scope = request.scope() != null ? request.scope() : "all";
        MavenConfig mavenConfig = request.maven() != null ? request.maven() : new MavenConfig();
        var cacheKey = indexCache.createKey(sourcePath, scope, request.targetModules(), mavenConfig);
        var cached = indexCache.getOrCompute(cacheKey, () -> analyzeUncached(
                sourcePath, scope, mavenConfig, request.targetModules(), progress));
        if (cached.cacheHit()) {
            progress.onEvent("cache", "INFO", "Analysis result loaded from cache");
        }
        return cached.response();
    }

    private AnalyzeResponse analyzeUncached(Path sourcePath, String scope, MavenConfig mavenConfig,
                                             List<String> requestedTargets,
                                             AnalysisProgressListener progress) {

        // P0-P1: 模块索引 + classpath 解析
        ModuleContext ctx = resolveModuleContext(sourcePath, scope, mavenConfig, requestedTargets,
                progress);

        // Step 1: 无依赖的独立分析并行执行
        CompletableFuture<List<EndpointInfo>> endpointsFuture = launchEndpointExtraction(
                sourcePath, ctx.classpathJars(), scope);
        CompletableFuture<CallGraphBuilder.BuildResult> callGraphFuture = launchCallGraphBuild(
                sourcePath, ctx.classpathJars(), scope);
        CompletableFuture<List<FindingItem>> findingsFuture = launchFindingDetection(
                sourcePath, ctx.classpathJars(), scope);

        // Step 2: 依赖 callgraph 的衍生分析
        var graph = callGraphFuture.thenApplyAsync(
                r -> r != null ? r.graph() : Map.<String, CallGraphNode>of(), analysisWorkerExecutor);
        var diagnostics = buildDiagnostics(callGraphFuture, ctx);

        var flowsFuture = endpointsFuture.thenCombineAsync(graph, (eps, g) -> {
            if (!isScope(scope, "flows", "all") || eps.isEmpty() || g.isEmpty())
                return List.<ExecutionFlow>of();
            return executionFlowTracer.trace(g, eps);
        }, analysisWorkerExecutor);
        var clustersFuture = graph.thenApplyAsync(g -> {
            if (!isScope(scope, "clusters", "all") || g.isEmpty())
                return List.<ClusterInfo>of();
            return communityClusterer.cluster(g);
        }, analysisWorkerExecutor);

        // Step 3: 收集结果
        List<EndpointInfo> endpoints = endpointsFuture.join();
        Map<String, CallGraphNode> callGraph = graph.join();
        List<FindingItem> findings = findingsFuture.join();
        List<ExecutionFlow> flows = flowsFuture.join();
        List<ClusterInfo> clusters = clustersFuture.join();
        AnalyzerDiagnostics diag = diagnostics.join();

        AnalyzeResponse response = new AnalyzeResponse(endpoints, callGraph, findings, flows, clusters, diag);
        logSummary(scope, endpoints, callGraph, findings, flows, clusters, diag);
        return response;
    }

    // ====== 模块上下文解析 ======

    private record ModuleContext(
            MavenModuleIndex index,
            List<String> targetModules,
            List<Path> classpathJars,
            ClasspathResult cpResult) {
    }

    private ModuleContext resolveModuleContext(Path sourcePath, String scope,
                                                MavenConfig mavenConfig,
                                                List<String> explicitTargets,
                                                AnalysisProgressListener progress) {
        MavenModuleIndex moduleIndex = sourceFileScanner.getCurrentModuleIndex(sourcePath);
        if (moduleIndex != null) {
            log.info("[POM] Module index built: {} modules, rootPom={}",
                    moduleIndex.getModuleCount(), moduleIndex.getRootPom());
        } else {
            log.info("[POM] No Maven module index (non-Maven project or scan failed)");
        }

        List<String> targetModules = resolveTargetModules(explicitTargets, moduleIndex);

        ClasspathResult cpResult = moduleIndex != null && targetModules != null && !targetModules.isEmpty()
                ? classpathResolver.resolve(moduleIndex, targetModules, mavenConfig, progress)
                : classpathResolver.resolve(sourcePath, mavenConfig, progress);

        List<Path> classpathJars = cpResult.isAvailable()
                ? cpResult.getJars().stream().map(Path::of).toList()
                : List.of();

        log.info("Classpath: available={} source={} jars={}",
                cpResult.isAvailable(), cpResult.getSource(), cpResult.getJars().size());

        return new ModuleContext(moduleIndex, targetModules, classpathJars, cpResult);
    }

    private List<String> resolveTargetModules(List<String> explicitTargets, MavenModuleIndex moduleIndex) {
        if (explicitTargets != null && !explicitTargets.isEmpty()) return explicitTargets;
        if (moduleIndex == null) return null;
        log.info("[AUTO_DETECT] No target modules specified, running classification...");
        moduleClassifier.classifyAll(moduleIndex);
        var targets = moduleClassifier.selectTargets(moduleIndex);
        var result = targets.stream().map(MavenModule::getDisplayName).toList();
        log.info("[AUTO_DETECT] Selected {} target modules: {}", result.size(), result);
        return result;
    }

    // ====== 并行分析启动 ======

    private CompletableFuture<List<EndpointInfo>> launchEndpointExtraction(
            Path sourcePath, List<Path> cp, String scope) {
        if (!isScope(scope, "endpoints", "all", "flows")) return CompletableFuture.completedFuture(List.of());
        return CompletableFuture.supplyAsync(
                () -> controllerExtractor.extract(sourcePath, cp), analysisWorkerExecutor);
    }

    private CompletableFuture<CallGraphBuilder.BuildResult> launchCallGraphBuild(
            Path sourcePath, List<Path> cp, String scope) {
        if (!isScope(scope, "callgraph", "all", "flows", "clusters"))
            return CompletableFuture.completedFuture(null);
        return CompletableFuture.supplyAsync(
                () -> callGraphBuilder.build(sourcePath, cp), analysisWorkerExecutor);
    }

    private CompletableFuture<List<FindingItem>> launchFindingDetection(
            Path sourcePath, List<Path> cp, String scope) {
        if (!isScope(scope, "all")) return CompletableFuture.completedFuture(List.of());
        return CompletableFuture.supplyAsync(
                () -> findingDetector.detect(sourcePath, cp), analysisWorkerExecutor);
    }

    // ====== Diagnostics 组装 ======

    private CompletableFuture<AnalyzerDiagnostics> buildDiagnostics(
            CompletableFuture<CallGraphBuilder.BuildResult> resultFuture, ModuleContext ctx) {
        return resultFuture.thenApplyAsync(result -> {
            AnalyzerDiagnostics diag = result != null ? result.diagnostics() : new AnalyzerDiagnostics();
            if (diag == null) return null;
            diag.setClasspathAvailable(ctx.cpResult().isAvailable());
            diag.setJarCount(ctx.cpResult().getJars().size());
            diag.setClasspathSource(ctx.cpResult().getSource());
            diag.setClasspathWarnings(ctx.cpResult().getWarnings());
            diag.setClasspathErrors(ctx.cpResult().getErrors());
            diag.setClasspathCommand(ctx.cpResult().getCommand());
            diag.setClasspathExitCode(ctx.cpResult().getExitCode());
            diag.setClasspathDurationMs(ctx.cpResult().getDurationMs());
            diag.setClasspathStdoutTail(ctx.cpResult().getStdoutTail());
            diag.setClasspathStderrTail(ctx.cpResult().getStderrTail());
            diag.setClasspathTimedOut(ctx.cpResult().isTimedOut());

            if (ctx.index() != null) {
                diag.setRootPom(ctx.index().getRootPom() != null
                        ? ctx.index().getRootPom().toString() : null);
                diag.setModuleCount(ctx.index().getModuleCount());
                diag.setSourceRootCount(ctx.index().getAllSourceRoots().size());
                diag.setModules(ctx.index().getModules().stream()
                        .map(MavenModule::getDisplayName).toList());
                diag.setApplicationModuleCount(ctx.index().getApplicationModuleCount());
                diag.setBusinessModuleCount(ctx.index().getBusinessModuleCount());
                diag.setLibraryModuleCount(ctx.index().getLibraryModuleCount());
                diag.setBomModuleCount(ctx.index().getBomModuleCount());
                diag.setModuleTypes(ctx.index().getModules().stream()
                        .filter(m -> !m.isAggregator())
                        .collect(Collectors.toMap(
                                MavenModule::getDisplayName,
                                m -> m.getModuleType().name())));
            }
            if (ctx.targetModules() != null) {
                diag.setClasspathTargetModules(ctx.targetModules());
            }
            return diag;
        }, analysisWorkerExecutor);
    }

    // ====== 辅助方法 ======

    private static boolean isScope(String actual, String... candidates) {
        for (String c : candidates) if (c.equals(actual)) return true;
        return false;
    }

    private void logSummary(String scope, List<EndpointInfo> endpoints,
                             Map<String, CallGraphNode> callGraph, List<FindingItem> findings,
                             List<ExecutionFlow> flows, List<ClusterInfo> clusters,
                             AnalyzerDiagnostics diagnostics) {
        log.info("白盒分析完成: scope={} endpoints={} callgraph_nodes={} findings={} flows={} clusters={}",
                scope, endpoints.size(), callGraph.size(), findings.size(), flows.size(), clusters.size());
        if (diagnostics != null) {
            log.info("解析诊断: files={}/{} calls={} H={} M={} U={} cp={} jars={}",
                    diagnostics.getParsedFileCount(), diagnostics.getTotalSourceFiles(),
                    diagnostics.getTotalCalls(), diagnostics.getResolvedHigh(),
                    diagnostics.getResolvedMedium(), diagnostics.getUnresolved(),
                    diagnostics.getClasspathSource(), diagnostics.getJarCount());
        }
    }
}
