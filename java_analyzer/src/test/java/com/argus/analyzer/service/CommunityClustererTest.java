package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.ClusterInfo;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class CommunityClustererTest {

    private final CommunityClusterer clusterer = new CommunityClusterer();

    @Test
    void shouldReturnEmptyForEmptyGraph() {
        List<ClusterInfo> clusters = clusterer.cluster(Map.of());
        assertThat(clusters).isEmpty();
    }

    @Test
    void shouldClusterTwoDisconnectedGroups() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();

        // Group A: UserController → UserService → UserRepository
        graph.put("com.user.UserController#getUser",
                node("com.user.UserController", "getUser", "com.user.UserService#findById"));
        graph.put("com.user.UserService#findById",
                node("com.user.UserService", "findById", "com.user.UserRepository#findById"));
        graph.put("com.user.UserRepository#findById",
                node("com.user.UserRepository", "findById"));

        // Group B: OrderController → OrderService → OrderRepository
        graph.put("com.order.OrderController#create",
                node("com.order.OrderController", "create", "com.order.OrderService#create"));
        graph.put("com.order.OrderService#create",
                node("com.order.OrderService", "create", "com.order.OrderRepository#save"));
        graph.put("com.order.OrderRepository#save",
                node("com.order.OrderRepository", "save"));

        List<ClusterInfo> clusters = clusterer.cluster(graph);

        assertThat(clusters).hasSize(2);
        // Each cluster should have 3 members
        for (ClusterInfo cluster : clusters) {
            assertThat(cluster.getMemberCount()).isEqualTo(3);
        }
    }

    @Test
    void shouldClusterTightlyConnectedGroup() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();

        // All in same package, heavily interconnected
        graph.put("com.payment.PaymentController#pay",
                node("com.payment.PaymentController", "pay", "com.payment.PaymentService#process"));
        graph.put("com.payment.PaymentService#process",
                node("com.payment.PaymentService", "process", "com.payment.GatewayClient#charge"));
        graph.put("com.payment.PaymentService#refund",
                node("com.payment.PaymentService", "refund", "com.payment.GatewayClient#reverse"));
        graph.put("com.payment.GatewayClient#charge",
                node("com.payment.GatewayClient", "charge"));
        graph.put("com.payment.GatewayClient#reverse",
                node("com.payment.GatewayClient", "reverse"));

        List<ClusterInfo> clusters = clusterer.cluster(graph);

        // All nodes may be in one cluster or split into few — verify no overlap and all accounted for
        int totalMembers = clusters.stream().mapToInt(ClusterInfo::getMemberCount).sum();
        assertThat(totalMembers).isEqualTo(5);
        assertThat(clusters).allMatch(c -> c.getMemberCount() >= 1);
    }

    @Test
    void shouldHandleIsolatedNodes() {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("A#methodA", node("A", "methodA"));
        graph.put("B#methodB", node("B", "methodB"));

        List<ClusterInfo> clusters = clusterer.cluster(graph);

        // Isolated nodes with no edges — each gets own cluster
        assertThat(clusters).hasSize(2);
    }

    // ---- helpers

    private CallGraphNode node(String className, String methodName, String... callees) {
        return new CallGraphNode(className, methodName, methodName + "()", List.of(callees));
    }
}
