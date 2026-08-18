package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.CallEdge;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.EndpointInfo;
import com.argus.analyzer.domain.model.ExecutionFlow;
import com.argus.analyzer.domain.model.FlowStep;
import com.argus.analyzer.domain.model.MethodKey;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * 执行流追踪（O-11 起实现 {@link AnalysisPass}，无状态、线程安全；消费
 * {@code CALL_GRAPH + ENDPOINTS}，产出 {@code FLOWS}，失败可显式降级）。
 */
public class ExecutionFlowTracer implements AnalysisPass {

    private static final Logger log = LoggerFactory.getLogger(ExecutionFlowTracer.class);
    private static final int MAX_DEPTH = 20;

    @Override
    public String id() {
        return "flows";
    }

    @Override
    public Capability produced() {
        return Capability.FLOWS;
    }

    @Override
    public Set<Capability> requires() {
        return Set.of(Capability.CALL_GRAPH, Capability.ENDPOINTS);
    }

    @Override
    public boolean required() {
        return false;
    }

    @Override
    public AnalysisContribution run(AnalysisContext context) {
        return guarded(context, () -> {
            Map<String, CallGraphNode> graph = context.get(Capability.CALL_GRAPH);
            List<EndpointInfo> endpoints = context.get(Capability.ENDPOINTS);
            if (graph == null || graph.isEmpty() || endpoints == null || endpoints.isEmpty()) {
                return new AnalysisContribution(Capability.FLOWS, List.<ExecutionFlow>of());
            }
            return new AnalysisContribution(Capability.FLOWS,
                    trace(graph, endpoints, context.progress()));
        });
    }

    public List<ExecutionFlow> trace(Map<String, CallGraphNode> callGraph, List<EndpointInfo> endpoints) {
        return trace(callGraph, endpoints, AnalysisProgressListener.NOOP);
    }

    /**
     * 追踪执行流，支持协作取消（O-04）：逐端点与 DFS 每层检查
     * {@code progress.isCancelled()}，取消时抛 {@link JobCancelledException}。
     */
    public List<ExecutionFlow> trace(Map<String, CallGraphNode> callGraph, List<EndpointInfo> endpoints,
                                     AnalysisProgressListener progress) {
        List<ExecutionFlow> flows = new ArrayList<>();

        Set<String> allKeys = callGraph.keySet();

        for (EndpointInfo ep : endpoints) {
            if (progress.isCancelled()) {
                throw new JobCancelledException("Execution flow tracing cancelled");
            }
            String entryKey = MethodKey.nameKey(ep.controllerClass(), ep.controllerMethod());
            if (!allKeys.contains(entryKey)) {
                continue;
            }

            List<FlowStep> steps = new ArrayList<>();
            Set<String> visited = new HashSet<>();
            Set<String> pathNodes = new HashSet<>();
            dfs(callGraph, entryKey, 0, visited, pathNodes, steps, progress);

            int maxDepth = steps.stream().mapToInt(FlowStep::depth).max().orElse(0);
            flows.add(new ExecutionFlow(entryKey, steps, maxDepth));
        }

        return flows;
    }

    private void dfs(Map<String, CallGraphNode> callGraph, String currentKey,
                     int depth, Set<String> visited, Set<String> pathNodes, List<FlowStep> steps,
                     AnalysisProgressListener progress) {
        if (progress.isCancelled()) {
            throw new JobCancelledException("Execution flow tracing cancelled");
        }
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
                    dfs(callGraph, calleeKey, depth + 1, visited, pathNodes, steps, progress);
                } else {
                    // External / unresolved call — record as leaf at next depth
                    String clazz = MethodKey.classNameOf(calleeKey);
                    String method = MethodKey.methodNameOf(calleeKey);
                    steps.add(new FlowStep(depth + 1, calleeKey, clazz, method));
                }
            }
        } finally {
            pathNodes.remove(currentKey);
        }
    }
}
