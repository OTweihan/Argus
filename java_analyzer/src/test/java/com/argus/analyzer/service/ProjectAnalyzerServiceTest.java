package com.argus.analyzer.service;

import com.argus.analyzer.application.ClasspathResolver;
import com.argus.analyzer.application.PassExecutor;
import com.argus.analyzer.application.PlanRegistry;
import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.AnalysisScope;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.ClusterInfo;
import com.argus.analyzer.domain.model.EndpointInfo;
import com.argus.analyzer.domain.model.ExecutionFlow;
import com.argus.analyzer.domain.model.FindingItem;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.ModuleClassifier;
import com.argus.analyzer.support.ProjectIndexCache;
import com.argus.analyzer.support.SourceFileScanner;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 核心分析编排单测（无需 Spring Context，O-11 验收标准）。
 */
class ProjectAnalyzerServiceTest {

    @FunctionalInterface
    private interface PassBody {
        AnalysisContribution run(AnalysisContext context);
    }

    @TempDir
    Path sourceDir;

    private ExecutorService executor;
    private PlanRegistry planRegistry;
    private ClasspathResolver classpathResolver;
    private SourceFileScanner sourceFileScanner;
    private ModuleClassifier moduleClassifier;
    private ProjectAnalyzerService service;

    @BeforeEach
    void setUp() {
        executor = Executors.newCachedThreadPool();
        EndpointInfo endpoint = new EndpointInfo(
                "/api/users", "GET", "com.demo.UserController", "getUser", List.of("id"), "User");
        FindingItem finding = new FindingItem(
                "EMPTY_CATCH", "MEDIUM", "t", "d", "A.java", 1, "snippet", "ERROR_HANDLING", "HIGH");
        ExecutionFlow flow = new ExecutionFlow("com.demo.UserController#getUser", List.of(), 0);
        ClusterInfo cluster = new ClusterInfo("cluster_0", "demo", List.of("A#m"));
        planRegistry = PlanRegistry.of(List.of(
                pass("endpoints", Capability.ENDPOINTS, ctx ->
                        new AnalysisContribution(Capability.ENDPOINTS, List.of(endpoint))),
                pass("callgraph", Capability.CALL_GRAPH, ctx ->
                        new AnalysisContribution(Capability.CALL_GRAPH,
                                Map.<String, CallGraphNode>of("A#m", new CallGraphNode("A", "m", "()V", List.of())))),
                pass("findings", Capability.FINDINGS, ctx ->
                        new AnalysisContribution(Capability.FINDINGS, List.of(finding))),
                pass("flows", Capability.FLOWS, ctx ->
                        new AnalysisContribution(Capability.FLOWS, List.of(flow)),
                        Capability.CALL_GRAPH, Capability.ENDPOINTS),
                pass("clusters", Capability.CLUSTERS, ctx ->
                        new AnalysisContribution(Capability.CLUSTERS, List.of(cluster)),
                        Capability.CALL_GRAPH)));

        classpathResolver = mock(ClasspathResolver.class);
        sourceFileScanner = mock(SourceFileScanner.class);
        moduleClassifier = mock(ModuleClassifier.class);
        when(classpathResolver.resolve(any(Path.class), any(MavenConfig.class),
                any(com.argus.analyzer.domain.AnalysisProgressListener.class)))
                .thenReturn(ClasspathResult.fromJars(List.of(), "mock-source"));

        service = new ProjectAnalyzerService(
                planRegistry,
                new PassExecutor(executor),
                new ProjectIndexCache(),
                classpathResolver,
                sourceFileScanner,
                moduleClassifier);
    }

    @AfterEach
    void tearDown() {
        executor.shutdownNow();
    }

    private static AnalysisPass pass(String id, Capability produced,
                                     PassBody body, Capability... requires) {
        return new AnalysisPass() {
            @Override public String id() { return id; }
            @Override public Capability produced() { return produced; }
            @Override public Set<Capability> requires() { return Set.of(requires); }
            @Override public boolean required() { return true; }
            @Override public AnalysisContribution run(AnalysisContext context) {
                return body.run(context);
            }
        };
    }

    private AnalysisCommand command(AnalysisScope scope) {
        return new AnalysisCommand(sourceDir, scope, List.of(), "req-1", null, "rev-1", null);
    }

    @Test
    void allScopeRunsAllPassesAndMergesDiagnostics() {
        AnalysisResult result = service.analyze(command(AnalysisScope.ALL),
                new MavenConfig(), (stage, level, message) -> {});

        assertThat(result.endpoints()).hasSize(1);
        assertThat(result.endpoints().get(0).path()).isEqualTo("/api/users");
        assertThat(result.callGraph()).containsOnlyKeys("A#m");
        assertThat(result.findings()).hasSize(1);
        assertThat(result.findings().get(0).ruleId()).isEqualTo("EMPTY_CATCH");
        assertThat(result.executionFlows()).hasSize(1);
        assertThat(result.clusters()).hasSize(1);
        // classpath 诊断合并
        assertThat(result.diagnostics()).isNotNull();
        assertThat(result.diagnostics().isClasspathAvailable()).isTrue();
        assertThat(result.diagnostics().getClasspathSource()).isEqualTo("mock-source");
        assertThat(result.diagnostics().getPassFailures()).isEmpty();
    }

    @Test
    void endpointsScopeRunsOnlyEndpointsPass() {
        AnalysisResult result = service.analyze(command(AnalysisScope.ENDPOINTS),
                new MavenConfig(), (stage, level, message) -> {});

        assertThat(result.endpoints()).hasSize(1);
        assertThat(result.callGraph()).isEmpty();
        assertThat(result.findings()).isEmpty();
        assertThat(result.executionFlows()).isEmpty();
        assertThat(result.clusters()).isEmpty();
    }

    @Test
    void modulesScopeRunsNoPassButStillResolvesClasspath() {
        AnalysisResult result = service.analyze(command(AnalysisScope.MODULES),
                new MavenConfig(), (stage, level, message) -> {});

        assertThat(result.endpoints()).isEmpty();
        assertThat(result.callGraph()).isEmpty();
        assertThat(result.diagnostics().isClasspathAvailable()).isTrue();
    }

    @Test
    void nonModuleProjectDoesNotInvokeModuleClassifier() {
        service.analyze(command(AnalysisScope.ALL), new MavenConfig(), (stage, level, message) -> {});
        verify(moduleClassifier, never()).classifyAll(any(), any());
        verify(classpathResolver).resolve(eq(sourceDir), any(MavenConfig.class),
                any(com.argus.analyzer.domain.AnalysisProgressListener.class));
    }
}
