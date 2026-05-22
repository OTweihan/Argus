package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.EndpointInfo;
import com.argus.analyzer.api.dto.ExecutionFlow;
import com.argus.analyzer.api.dto.FlowStep;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class ExecutionFlowTracer {

    private static final Logger log = LoggerFactory.getLogger(ExecutionFlowTracer.class);
    private static final int MAX_DEPTH = 20;

    public List<ExecutionFlow> trace(Map<String, CallGraphNode> callGraph, List<EndpointInfo> endpoints) {
        List<ExecutionFlow> flows = new ArrayList<>();

        Set<String> allKeys = callGraph.keySet();

        for (EndpointInfo ep : endpoints) {
            String entryKey = ep.getControllerClass() + "#" + ep.getControllerMethod();
            if (!allKeys.contains(entryKey)) {
                continue;
            }

            List<FlowStep> steps = new ArrayList<>();
            Set<String> visited = new HashSet<>();
            dfs(callGraph, entryKey, 0, visited, steps);

            int maxDepth = steps.stream().mapToInt(FlowStep::getDepth).max().orElse(0);
            flows.add(new ExecutionFlow(entryKey, steps, maxDepth));
        }

        return flows;
    }

    private void dfs(Map<String, CallGraphNode> callGraph, String currentKey,
                     int depth, Set<String> visited, List<FlowStep> steps) {
        if (depth > MAX_DEPTH || visited.contains(currentKey)) {
            return;
        }

        visited.add(currentKey);

        CallGraphNode node = callGraph.get(currentKey);
        if (node == null) {
            return;
        }

        steps.add(new FlowStep(depth, currentKey, node.getClassName(), node.getMethodName()));

        for (String callee : node.getCallees()) {
            if (callGraph.containsKey(callee)) {
                dfs(callGraph, callee, depth + 1, visited, steps);
            } else {
                // External / unresolved call — record as leaf at next depth
                String[] parts = callee.split("#", 2);
                String clazz = parts.length > 1 ? parts[0] : "";
                String method = parts.length > 1 ? parts[1] : callee;
                steps.add(new FlowStep(depth + 1, callee, clazz, method));
            }
        }
    }
}
