package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallEdge;
import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.ClusterInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

@Service
public class CommunityClusterer {

    private static final Logger log = LoggerFactory.getLogger(CommunityClusterer.class);
    private static final int MAX_ITERATIONS = 50;

    public List<ClusterInfo> cluster(Map<String, CallGraphNode> callGraph) {
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
