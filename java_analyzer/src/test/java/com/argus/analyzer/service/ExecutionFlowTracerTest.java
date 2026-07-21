package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallEdge;
import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.Confidence;
import com.argus.analyzer.api.dto.EndpointInfo;
import com.argus.analyzer.api.dto.ExecutionFlow;
import com.argus.analyzer.api.dto.FlowStep;
import com.argus.analyzer.api.dto.ResolutionType;
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
