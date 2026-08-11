package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisPassException;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.CallEdge;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.ClusterInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * 社区聚类（O-11 起实现 {@link AnalysisPass}，无状态、线程安全；消费
 * {@code CALL_GRAPH}，产出 {@code CLUSTERS}，失败可显式降级）。
 */
public class CommunityClusterer implements AnalysisPass {

    private static final Logger log = LoggerFactory.getLogger(CommunityClusterer.class);
    private static final int MAX_ITERATIONS = 50;

    @Override
    public String id() {
        return "clusters";
    }

    @Override
    public Capability produced() {
        return Capability.CLUSTERS;
    }

    @Override
    public Set<Capability> requires() {
        return Set.of(Capability.CALL_GRAPH);
    }

    @Override
    public boolean required() {
        return false;
    }

    @Override
    public AnalysisContribution run(AnalysisContext context) {
        try {
            Map<String, CallGraphNode> graph = context.get(Capability.CALL_GRAPH);
            if (graph == null || graph.isEmpty()) {
                return new AnalysisContribution(Capability.CLUSTERS, List.<ClusterInfo>of());
            }
            return new AnalysisContribution(Capability.CLUSTERS, cluster(graph, context.progress()));
        } catch (JobCancelledException cancelled) {
            throw cancelled;
        } catch (RuntimeException error) {
            throw new AnalysisPassException(id(), error);
        }
    }

    public List<ClusterInfo> cluster(Map<String, CallGraphNode> callGraph) {
        return cluster(callGraph, AnalysisProgressListener.NOOP);
    }

    /**
     * 社区聚类，支持协作取消（O-04）：迭代传播的安全边界检查
     * {@code progress.isCancelled()}，取消时抛 {@link JobCancelledException}。
     */
    public List<ClusterInfo> cluster(Map<String, CallGraphNode> callGraph,
                                     AnalysisProgressListener progress) {
        if (callGraph == null || callGraph.isEmpty()) {
            return List.of();
        }

        // Build adjacency (undirected) from call graph callees
        Map<String, Set<String>> adjacency = new HashMap<>();
        for (var entry : callGraph.entrySet()) {
            String caller = entry.getKey();
            adjacency.computeIfAbsent(caller, k -> new HashSet<>());

            for (CallEdge callee : entry.getValue().calleeDetails()) {
                String calleeKey = callee.to();
                if (callGraph.containsKey(calleeKey)) {
                    adjacency.computeIfAbsent(caller, k -> new HashSet<>()).add(calleeKey);
                    adjacency.computeIfAbsent(calleeKey, k -> new HashSet<>()).add(caller);
                }
            }
        }

        // Label propagation
        Map<String, String> labels = new HashMap<>();
        for (String key : adjacency.keySet()) {
            labels.put(key, key);
        }

        boolean changed = true;
        int iterations = 0;
        while (changed && iterations < MAX_ITERATIONS) {
            if (progress.isCancelled()) {
                throw new JobCancelledException("Community clustering cancelled");
            }
            changed = false;
            iterations++;

            List<String> nodes = new ArrayList<>(adjacency.keySet());
            Collections.shuffle(nodes, new Random(42));

            for (String node : nodes) {
                Set<String> neighbors = adjacency.get(node);
                if (neighbors.isEmpty()) continue;

                Map<String, Long> freq = new HashMap<>();
                for (String neighbor : neighbors) {
                    String neighborLabel = labels.get(neighbor);
                    if (neighborLabel != null) {
                        freq.merge(neighborLabel, 1L, Long::sum);
                    }
                }

                if (freq.isEmpty()) continue;

                String bestLabel = freq.entrySet().stream()
                        .max(Map.Entry.<String, Long>comparingByValue()
                                .thenComparing(Map.Entry.comparingByKey()))
                        .get().getKey();

                if (!bestLabel.equals(labels.get(node))) {
                    labels.put(node, bestLabel);
                    changed = true;
                }
            }
        }

        // Group by label
        Map<String, List<String>> groups = new HashMap<>();
        for (var entry : labels.entrySet()) {
            groups.computeIfAbsent(entry.getValue(), k -> new ArrayList<>()).add(entry.getKey());
        }

        // Build ClusterInfo list
        List<ClusterInfo> clusters = new ArrayList<>();
        int clusterIdx = 0;
        for (var entry : groups.entrySet()) {
            List<String> members = entry.getValue();
            String label = deriveLabel(members);
            clusters.add(new ClusterInfo("cluster_" + clusterIdx++, label, members));
        }

        return clusters;
    }

    private String deriveLabel(List<String> memberKeys) {
        // Try to find a common package prefix
        Set<String> packages = new HashSet<>();
        for (String key : memberKeys) {
            int hashIdx = key.lastIndexOf('#');
            if (hashIdx > 0) {
                String className = key.substring(0, hashIdx);
                int dotIdx = className.lastIndexOf('.');
                if (dotIdx > 0) {
                    packages.add(className.substring(0, dotIdx));
                }
            }
        }

        if (packages.size() == 1) {
            String pkg = packages.iterator().next();
            return pkg.substring(pkg.lastIndexOf('.') + 1);
        }

        // Prefer controller-based naming
        for (String key : memberKeys) {
            int hashIdx = key.lastIndexOf('#');
            if (hashIdx > 0) {
                String className = key.substring(0, hashIdx);
                if (className.contains("Controller")) {
                    return className.substring(className.lastIndexOf('.') + 1)
                            .replace("Controller", "");
                }
            }
        }

        // Fallback: most common simple class name prefix
        return "Cluster";
    }
}
