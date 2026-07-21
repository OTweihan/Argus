package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallEdge;
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
            String entryKey = ep.controllerClass() + "#" + ep.controllerMethod();
            if (!allKeys.contains(entryKey)) {
                continue;
            }

            List<FlowStep> steps = new ArrayList<>();
            Set<String> visited = new HashSet<>();
            Set<String> pathNodes = new HashSet<>();
            dfs(callGraph, entryKey, 0, visited, pathNodes, steps);

            int maxDepth = steps.stream().mapToInt(FlowStep::depth).max().orElse(0);
            flows.add(new ExecutionFlow(entryKey, steps, maxDepth));
        }

        return flows;
    }

    private void dfs(Map<String, CallGraphNode> callGraph, String currentKey,
                     int depth, Set<String> visited, Set<String> pathNodes, List<FlowStep> steps) {
        if (depth > MAX_DEPTH || pathNodes.contains(currentKey)) {
            return;
        }

        pathNodes.add(currentKey);

        try {
            CallGraphNode node = callGraph.get(currentKey);
            if (node == null) {
                return;
            }

            // 仅当节点首次被访问时才添加步骤（全局去重），
            // 但允许通过不同路径重新进入以追踪其下游调用者。
            if (visited.add(currentKey)) {
                steps.add(new FlowStep(depth, currentKey, node.className(), node.methodName()));
            }

            for (CallEdge callee : node.calleeDetails()) {
                String calleeKey = callee.to();
                if (callGraph.containsKey(calleeKey)) {
                    dfs(callGraph, calleeKey, depth + 1, visited, pathNodes, steps);
                } else {
                    // External / unresolved call — record as leaf at next depth
                    String[] parts = calleeKey.split("#", 2);
                    String clazz = parts.length > 1 ? parts[0] : "";
                    String method = parts.length > 1 ? parts[1] : calleeKey;
                    steps.add(new FlowStep(depth + 1, calleeKey, clazz, method));
                }
            }
        } finally {
            pathNodes.remove(currentKey);
        }
    }
}
