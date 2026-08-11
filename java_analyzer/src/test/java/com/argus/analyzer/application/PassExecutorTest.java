package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.AnalysisScope;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.CallGraphNode;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PassExecutorTest {

    @FunctionalInterface
    private interface PassBody {
        AnalysisContribution run(AnalysisContext context);
    }

    private ExecutorService executor;
    private PassExecutor passExecutor;

    @BeforeEach
    void setUp() {
        executor = Executors.newCachedThreadPool();
        passExecutor = new PassExecutor(executor);
    }

    @AfterEach
    void tearDown() {
        executor.shutdownNow();
    }

    private static AnalysisPass pass(String id, Capability produced, boolean required,
                                     PassBody body, Capability... requires) {
        return new AnalysisPass() {
            @Override public String id() { return id; }
            @Override public Capability produced() { return produced; }
            @Override public Set<Capability> requires() { return Set.of(requires); }
            @Override public boolean required() { return required; }
            @Override public AnalysisContribution run(AnalysisContext context) {
                return body.run(context);
            }
        };
    }

    private static AnalysisPass pass(String id, Capability produced, boolean required,
                                     Capability... requires) {
        return pass(id, produced, required, ctx -> new AnalysisContribution(produced, List.of()), requires);
    }

    private static AnalysisContext context() {
        var command = new AnalysisCommand(Path.of("C:\\src"), AnalysisScope.ALL,
                List.of(), null, null, null, null);
        return new AnalysisContext(command.sourcePath(), command, List.of(), null);
    }

    @Test
    void emptyPlanProducesEmptyResult() {
        AnalysisResult result = passExecutor.execute(List.of(), context());
        assertThat(result.endpoints()).isEmpty();
        assertThat(result.callGraph()).isEmpty();
        assertThat(result.diagnostics()).isNotNull();
        assertThat(result.diagnostics().getPassFailures()).isEmpty();
    }

    @Test
    void executesLeafPassesAndDependentPasses() {
        var graph = Map.of("a#m", new CallGraphNode("a", "m", "()V", List.of()));
        AnalysisPass endpoints = pass("endpoints", Capability.ENDPOINTS, true,
                ctx -> new AnalysisContribution(Capability.ENDPOINTS, List.of("ep-1")));
        AnalysisPass callgraph = pass("callgraph", Capability.CALL_GRAPH, true,
                ctx -> new AnalysisContribution(Capability.CALL_GRAPH, graph));
        AnalysisPass flows = pass("flows", Capability.FLOWS, false, ctx -> {
            Object eps = ctx.get(Capability.ENDPOINTS);
            Object g = ctx.get(Capability.CALL_GRAPH);
            assertThat(eps).isEqualTo(List.of("ep-1"));
            assertThat(g).isSameAs(graph);
            return new AnalysisContribution(Capability.FLOWS, List.of("flow-1"));
        }, Capability.CALL_GRAPH, Capability.ENDPOINTS);

        AnalysisResult result = passExecutor.execute(List.of(endpoints, callgraph, flows), context());

        assertThat(result.endpoints()).isEqualTo(List.of("ep-1"));
        assertThat(result.callGraph()).isSameAs(graph);
        assertThat(result.executionFlows()).isEqualTo(List.of("flow-1"));
        assertThat(result.diagnostics().getPassFailures()).isEmpty();
    }

    @Test
    void optionalPassFailureDegradesIntoDiagnostics() {
        List<String> events = new ArrayList<>();
        var command = new AnalysisCommand(Path.of("C:\\src"), AnalysisScope.ALL, List.of(), null, null, null, null);
        var context = new AnalysisContext(command.sourcePath(), command, List.of(),
                (stage, level, message) -> events.add(message));
        AnalysisPass callgraph = pass("callgraph", Capability.CALL_GRAPH, true,
                ctx -> new AnalysisContribution(Capability.CALL_GRAPH, Map.<String, CallGraphNode>of()));
        AnalysisPass flows = pass("flows", Capability.FLOWS, false, ctx -> {
            throw new IllegalStateException("flow tracer bug");
        }, Capability.CALL_GRAPH);

        AnalysisResult result = passExecutor.execute(List.of(callgraph, flows), context);

        assertThat(result.executionFlows()).isEmpty();
        assertThat(result.diagnostics().getPassFailures())
                .containsExactly("flows: flow tracer bug");
        assertThat(events).anyMatch(e -> e.contains("flows") && e.contains("degraded"));
    }

    @Test
    void requiredPassFailurePropagates() {
        AnalysisPass callgraph = pass("callgraph", Capability.CALL_GRAPH, true, ctx -> {
            throw new IllegalStateException("boom");
        });
        AnalysisPass flows = pass("flows", Capability.FLOWS, false, ctx ->
                new AnalysisContribution(Capability.FLOWS, List.of()), Capability.CALL_GRAPH);

        assertThatThrownBy(() -> passExecutor.execute(List.of(callgraph, flows), context()))
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("boom");
    }

    @Test
    void cancellationPropagatesEvenForOptionalPass() {
        AnalysisPass flows = pass("flows", Capability.FLOWS, false, ctx -> {
            throw new JobCancelledException("cancelled during flows");
        });

        assertThatThrownBy(() -> passExecutor.execute(List.of(flows), context()))
                .isInstanceOf(JobCancelledException.class)
                .hasMessageContaining("cancelled during flows");
    }

    @Test
    void fatalErrorPropagatesEvenForOptionalPass() {
        AnalysisPass flows = pass("flows", Capability.FLOWS, false, ctx -> {
            throw new OutOfMemoryError("fatal pass failure");
        });

        assertThatThrownBy(() -> passExecutor.execute(List.of(flows), context()))
                .isInstanceOf(OutOfMemoryError.class)
                .hasMessageContaining("fatal pass failure");
    }

    @Test
    void requiredFailureWaitsForSiblingPassToSettle() {
        CountDownLatch siblingStarted = new CountDownLatch(1);
        AtomicBoolean siblingFinished = new AtomicBoolean();
        AnalysisPass failing = pass("failing", Capability.ENDPOINTS, true, ctx -> {
            try {
                siblingStarted.await();
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(error);
            }
            throw new IllegalStateException("required pass failed");
        });
        AnalysisPass sibling = pass("sibling", Capability.CALL_GRAPH, true, ctx -> {
            siblingStarted.countDown();
            try {
                Thread.sleep(75);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(error);
            }
            siblingFinished.set(true);
            return new AnalysisContribution(Capability.CALL_GRAPH, Map.of());
        });

        assertThatThrownBy(() -> passExecutor.execute(List.of(failing, sibling), context()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("required pass failed");
        assertThat(siblingFinished)
                .as("同波任务必须在作业返回失败前结束")
                .isTrue();
    }

    @Test
    void rejectedSubmissionWaitsForAlreadySubmittedPass() {
        AtomicInteger submissions = new AtomicInteger();
        AtomicBoolean firstFinished = new AtomicBoolean();
        Executor rejectingExecutor = command -> {
            if (submissions.incrementAndGet() > 1) {
                throw new RejectedExecutionException("worker queue full");
            }
            executor.execute(command);
        };
        PassExecutor boundedPassExecutor = new PassExecutor(rejectingExecutor);
        AnalysisPass first = pass("first", Capability.ENDPOINTS, true, ctx -> {
            try {
                Thread.sleep(75);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(error);
            }
            firstFinished.set(true);
            return new AnalysisContribution(Capability.ENDPOINTS, List.of());
        });
        AnalysisPass rejected = pass("rejected", Capability.CALL_GRAPH, true);

        assertThatThrownBy(
                () -> boundedPassExecutor.execute(List.of(first, rejected), context()))
                .isInstanceOf(RejectedExecutionException.class)
                .hasMessageContaining("worker queue full");
        assertThat(firstFinished)
                .as("提交失败前已启动的 pass 必须先收敛")
                .isTrue();
    }

    @Test
    void degradedOptionalDependencyProducesReadableError() {
        // 可选 pass 失败未产出能力 → 下游必需 pass 依赖缺失 → 可读错误而非泛化"不应发生"。
        // flows 声明产出 FLOWS 且不依赖 CALL_GRAPH：缺失的 FLOWS 只能来自可选 pass 降级。
        AnalysisPass flows = pass("flows", Capability.FLOWS, false, ctx -> {
            throw new IllegalStateException("flows down");
        }, Capability.ENDPOINTS);
        AnalysisPass endpoints = pass("endpoints", Capability.ENDPOINTS, true,
                ctx -> new AnalysisContribution(Capability.ENDPOINTS, List.of()));
        AnalysisPass downstream = pass("downstream", Capability.FINDINGS, true, ctx -> {
            return new AnalysisContribution(Capability.FINDINGS, List.of());
        }, Capability.FLOWS);

        assertThatThrownBy(() -> passExecutor.execute(
                List.of(flows, endpoints, downstream), context()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("optional pass degradation removed capabilities [FLOWS]")
                .hasMessageContaining("downstream");
    }

    @Test
    void resultRecordedUnderPassDeclaredCapability() {
        // pass 声明的产出与 contribution 声称不一致时，以 pass 声明为准。
        AnalysisPass rogue = pass("rogue", Capability.ENDPOINTS, true, ctx -> {
            return new AnalysisContribution(Capability.FLOWS, List.of("leak"));
        });

        AnalysisResult result = passExecutor.execute(List.of(rogue), context());

        // contribution 声称 FLOWS 但 pass 声明产出 ENDPOINTS → 记录到 ENDPOINTS。
        assertThat(result.endpoints()).isEqualTo(List.of("leak"));
        assertThat(result.executionFlows()).isEmpty();
    }

    @Test
    void resultOrderMatchesPlanForReproducibility() {
        // 同一计划两次执行结果可重复（顺序按记录字段固定）。
        AnalysisPass endpoints = pass("endpoints", Capability.ENDPOINTS, true,
                ctx -> new AnalysisContribution(Capability.ENDPOINTS, List.of("ep-1", "ep-2")));
        AnalysisPass findings = pass("findings", Capability.FINDINGS, true,
                ctx -> new AnalysisContribution(Capability.FINDINGS, List.of("f-1")));
        AnalysisPass callgraph = pass("callgraph", Capability.CALL_GRAPH, true,
                ctx -> new AnalysisContribution(Capability.CALL_GRAPH, Map.<String, CallGraphNode>of()));

        AnalysisResult first = passExecutor.execute(List.of(endpoints, findings, callgraph), context());
        AnalysisResult second = passExecutor.execute(List.of(endpoints, findings, callgraph), context());

        // 内容逐字段可重复（AnalyzerDiagnostics 为可变对象，不做整体 record 相等比较）。
        assertThat(first.endpoints()).isEqualTo(second.endpoints());
        assertThat(first.findings()).isEqualTo(second.findings());
        assertThat(first.callGraph()).isEqualTo(second.callGraph());
        assertThat(first.executionFlows()).isEqualTo(second.executionFlows());
        assertThat(first.clusters()).isEqualTo(second.clusters());
        assertThat(first.endpoints()).isEqualTo(List.of("ep-1", "ep-2"));
        assertThat(first.findings()).isEqualTo(List.of("f-1"));
    }

    @Test
    void leafPassesMayRunConcurrently() throws InterruptedException {
        AtomicInteger concurrent = new AtomicInteger();
        AtomicInteger maxConcurrent = new AtomicInteger();
        AnalysisPass slow = pass("slow", Capability.ENDPOINTS, true, ctx -> {
            int now = concurrent.incrementAndGet();
            maxConcurrent.accumulateAndGet(now, Math::max);
            try {
                Thread.sleep(80);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            concurrent.decrementAndGet();
            return new AnalysisContribution(Capability.ENDPOINTS, List.of());
        });

        passExecutor.execute(List.of(slow, slow, slow), context());
        assertThat(maxConcurrent.get()).isGreaterThan(1);
    }
}
