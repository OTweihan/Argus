package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.model.CallEdge;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.Confidence;
import com.argus.analyzer.domain.model.EndpointInfo;
import com.argus.analyzer.domain.model.ExecutionFlow;
import com.argus.analyzer.domain.model.FlowStep;
import com.argus.analyzer.domain.model.ResolutionType;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ExecutionFlowTracerTest {

    private final ExecutionFlowTracer tracer = new ExecutionFlowTracer();

    @Test
    void shouldTraceSingleLevelChain() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("UserController#getUser", node("UserController", "getUser", "UserService#findById"));
        graph.put("UserService#findById", node("UserService", "findById"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/users/{id}", "GET", "UserController", "getUser", List.of("id"), "User")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).hasSize(1);
        ExecutionFlow flow = flows.getFirst();
        assertThat(flow.entryPoint()).isEqualTo("UserController#getUser");
        assertThat(flow.callDepth()).isEqualTo(1);
        assertThat(flow.steps()).hasSize(2);
        assertThat(flow.steps()).extracting(FlowStep::methodKey)
                .containsExactly("UserController#getUser", "UserService#findById");
    }

    @Test
    void shouldTraceDeepChain() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("UserController#getUser", node("UserController", "getUser", "UserService#findById"));
        graph.put("UserService#findById", node("UserService", "findById", "UserRepository#findById"));
        graph.put("UserRepository#findById", node("UserRepository", "findById"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/users/{id}", "GET", "UserController", "getUser", List.of("id"), "User")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).hasSize(1);
        ExecutionFlow flow = flows.getFirst();
        assertThat(flow.callDepth()).isEqualTo(2);
        assertThat(flow.steps()).extracting(FlowStep::methodKey)
                .containsExactly("UserController#getUser", "UserService#findById", "UserRepository#findById");
    }

    @Test
    void shouldTraceBranchingCalls() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("OrderController#create", node("OrderController", "create",
                "OrderService#create", "InventoryService#checkStock"));
        graph.put("OrderService#create", node("OrderService", "create", "OrderRepository#save"));
        graph.put("InventoryService#checkStock", node("InventoryService", "checkStock",
                "InventoryRepository#findBySku"));
        graph.put("OrderRepository#save", node("OrderRepository", "save"));
        graph.put("InventoryRepository#findBySku", node("InventoryRepository", "findBySku"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/orders", "POST", "OrderController", "create", List.of(), "Order")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).hasSize(1);
        ExecutionFlow flow = flows.getFirst();
        // Should visit all reachable nodes: controller → service branches → repos
        assertThat(flow.steps()).extracting(FlowStep::methodKey)
                .contains("OrderController#create", "OrderService#create", "InventoryService#checkStock");
    }

    /**
     * Regression test for visited/pathNodes separation (commit f3f8a9e).
     *
     * When a shared node (SharedService#transform) is reachable from two different
     * branches within the same endpoint's call graph, it must be:
     * 1. Re-entered per traversal path (so its downstream callees are NOT missed), but
     * 2. Emitted only once globally as a FlowStep (no duplicate entries).
     *
     * Before the fix, a single visited Set blocked re-entry entirely — the second
     * branch would stop at SharedService and skip RepositoryX entirely.
     *
     * <pre>
     * TestController#create
     * ├── ServiceA#process → SharedService#transform → RepositoryX#save
     * └── ServiceB#process → SharedService#transform → RepositoryX#save
     * </pre>
     */
    @Test
    void shouldTraceSharedNodeAcrossBranches() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("TestController#create", node("TestController", "create",
                "ServiceA#process", "ServiceB#process"));
        graph.put("ServiceA#process", node("ServiceA", "process",
                "SharedService#transform"));
        graph.put("ServiceB#process", node("ServiceB", "process",
                "SharedService#transform"));
        graph.put("SharedService#transform", node("SharedService", "transform",
                "RepositoryX#save"));
        graph.put("RepositoryX#save", node("RepositoryX", "save"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/test", "POST", "TestController", "create", List.of(), "void")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).hasSize(1);
        List<String> keys = flowSteps(flows.getFirst());

        // 1. All 5 unique nodes present — order independent
        assertThat(keys).containsExactlyInAnyOrder(
                "TestController#create",
                "ServiceA#process",
                "ServiceB#process",
                "SharedService#transform",
                "RepositoryX#save"
        );

        // 2. No duplicate entries (visited dedup works)
        assertThat(keys).doesNotHaveDuplicates();

        // 3. SharedService appears exactly once (visited dedup)
        assertThat(keys.stream()
                .filter(k -> k.equals("SharedService#transform"))
                .count()).isEqualTo(1);

        // 4. RepositoryX is present — proves DFS re-entered SharedService
        //    and traced its downstream callees (this was the lost node before the fix)
        assertThat(keys).contains("RepositoryX#save");

        // 5. ServiceB is present — proves the second branch was not skipped
        assertThat(keys).contains("ServiceB#process");

        // 6. Depth ≥ 2
        assertThat(flows.getFirst().callDepth()).isGreaterThanOrEqualTo(2);
    }

    @Test
    void shouldDetectCycles() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("A#methodA", node("A", "methodA", "B#methodB"));
        graph.put("B#methodB", node("B", "methodB", "C#methodC"));
        graph.put("C#methodC", node("C", "methodC", "A#methodA"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/test", "GET", "A", "methodA", List.of(), "void")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).hasSize(1);
        // Should terminate without infinite loop; A and B steps present; C found but A not re-visited
        assertThat(flowSteps(flows.getFirst())).doesNotHaveDuplicates();
    }

    @Test
    void shouldTreatExternalCallsAsLeaves() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("UserController#getUser", node("UserController", "getUser", "userService.findById"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/users/{id}", "GET", "UserController", "getUser", List.of("id"), "User")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).hasSize(1);
        ExecutionFlow flow = flows.getFirst();
        // External call recorded as leaf step
        assertThat(flow.steps()).extracting(FlowStep::methodKey)
                .containsExactly("UserController#getUser", "userService.findById");
        assertThat(flow.steps().get(1).depth()).isEqualTo(1);
    }

    @Test
    void shouldReturnEmptyForUnknownEntryPoint() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("SomeClass#someMethod", node("SomeClass", "someMethod"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/test", "GET", "NonExistent", "method", List.of(), "void")
        );

        List<ExecutionFlow> flows = tracer.trace(graph, endpoints);

        assertThat(flows).isEmpty();
    }

    @Test
    void shouldHandleEmptyGraphOrEndpoints() {
        assertThat(tracer.trace(Map.of(), List.of())).isEmpty();
        assertThat(tracer.trace(Map.of(), List.of(new EndpointInfo("/", "GET", "C", "m", List.of(), "void")))).isEmpty();
    }

    /**
     * 单流步数上限：稠密图全量展开时单流可达 O(节点数)，超过上限必须截断，
     * 并把截断记录写入 truncations、经 progress 发 WARN 事件。
     */
    @Test
    void shouldCapStepsPerFlowAndRecordTruncation() {
        ExecutionFlowTracer capped = new ExecutionFlowTracer(4, 100);
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        for (int i = 0; i < 9; i++) {
            graph.put("N" + i + "#m", node("N" + i, "m", "N" + (i + 1) + "#m"));
        }
        graph.put("N9#m", node("N9", "m"));

        List<String> warnings = new ArrayList<>();
        AnalysisProgressListener progress = (stage, level, message) -> {
            if ("WARN".equals(level)) warnings.add(message);
        };

        ExecutionFlowTracer.TraceOutcome outcome = capped.traceWithBudget(
                graph,
                List.of(new EndpointInfo("/t", "GET", "N0", "m", List.of(), "void")),
                progress);

        assertThat(outcome.flows()).hasSize(1);
        assertThat(flowSteps(outcome.flows().getFirst())).hasSize(4);
        assertThat(outcome.flows().getFirst().callDepth()).isEqualTo(3);
        assertThat(outcome.truncations()).containsExactly("N0#m: truncated at 4 steps (cap 4)");
        assertThat(warnings).singleElement().asString().contains("truncated");
    }

    /** 全局预算：耗尽后当前流截断、剩余端点整流跳过，且不再产生空流。 */
    @Test
    void shouldStopTracingWhenGlobalBudgetExhausted() {
        ExecutionFlowTracer bounded = new ExecutionFlowTracer(100, 6);
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("A#m", node("A", "m", "B#m"));
        graph.put("B#m", node("B", "m", "C#m"));
        graph.put("C#m", node("C", "m", "D#m"));
        graph.put("D#m", node("D", "m"));

        List<EndpointInfo> endpoints = List.of(
                new EndpointInfo("/a", "GET", "A", "m", List.of(), "void"),
                new EndpointInfo("/b", "GET", "B", "m", List.of(), "void"),
                new EndpointInfo("/c", "GET", "C", "m", List.of(), "void")
        );

        ExecutionFlowTracer.TraceOutcome outcome = bounded.traceWithBudget(
                graph, endpoints, AnalysisProgressListener.NOOP);

        // 端点 A 消耗 4 步；端点 B 只剩 2 步预算（截断）；端点 C 整流跳过，不产生空流。
        assertThat(outcome.flows()).hasSize(2);
        assertThat(flowSteps(outcome.flows().get(0))).containsExactly("A#m", "B#m", "C#m", "D#m");
        assertThat(flowSteps(outcome.flows().get(1))).containsExactly("B#m", "C#m");
        assertThat(outcome.truncations()).containsExactly(
                "B#m: truncated at 2 steps (cap 100)",
                "global step budget (6) exhausted; skipped 1 endpoint flow(s)");
    }

    /** 未触限时行为与旧实现一致：不产生截断记录。 */
    @Test
    void shouldNotRecordTruncationsWithinBudget() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("UserController#getUser",
                node("UserController", "getUser", "UserService#findById"));
        graph.put("UserService#findById", node("UserService", "findById"));

        ExecutionFlowTracer.TraceOutcome outcome = tracer.traceWithBudget(
                graph,
                List.of(new EndpointInfo("/users/{id}", "GET", "UserController", "getUser",
                        List.of("id"), "User")),
                AnalysisProgressListener.NOOP);

        assertThat(outcome.flows()).hasSize(1);
        assertThat(outcome.truncations()).isEmpty();
    }

    // ---- helpers

    private CallGraphNode node(String className, String methodName, String... callees) {
        List<CallEdge> edges = new ArrayList<>();
        for (String callee : callees) {
            edges.add(new CallEdge(
                callee, "", "", ResolutionType.UNRESOLVED, Confidence.UNKNOWN, List.of(), "", 0
            ));
        }
        return new CallGraphNode(className, methodName, methodName + "()", edges);
    }

    private List<String> flowSteps(ExecutionFlow flow) {
        return flow.steps().stream().map(FlowStep::methodKey).toList();
    }
}
