package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
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
 *
 * <p>体积防护：每端点独立 DFS，稠密图下全量展开最坏 O(端点×节点) 条
 * {@link FlowStep}。单流超过步数上限即截断，全部流共享全局步数预算，耗尽后
 * 停止追踪剩余端点；截断经 progress 发 WARN 事件并记入
 * {@code AnalyzerDiagnostics.flowTruncations}，不静默丢数据。</p>
 */
public class ExecutionFlowTracer implements AnalysisPass {

    private static final Logger log = LoggerFactory.getLogger(ExecutionFlowTracer.class);
    private static final int MAX_DEPTH = 20;

    /** 单流步数上限：超限截断该流（下游不再展开）。 */
    private static final int DEFAULT_MAX_STEPS_PER_FLOW = 400;
    /** 所有流共享的全局步数预算：耗尽后跳过剩余端点。 */
    private static final int DEFAULT_MAX_TOTAL_STEPS = 5000;

    private final int maxStepsPerFlow;
    private final int maxTotalSteps;

    public ExecutionFlowTracer() {
        this(DEFAULT_MAX_STEPS_PER_FLOW, DEFAULT_MAX_TOTAL_STEPS);
    }

    ExecutionFlowTracer(int maxStepsPerFlow, int maxTotalSteps) {
        this.maxStepsPerFlow = maxStepsPerFlow;
        this.maxTotalSteps = maxTotalSteps;
    }

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
            TraceOutcome outcome = traceWithBudget(graph, endpoints, context.progress());
            if (outcome.truncations().isEmpty()) {
                return new AnalysisContribution(Capability.FLOWS, outcome.flows());
            }
            AnalyzerDiagnostics diagnostics = new AnalyzerDiagnostics();
            diagnostics.setFlowTruncations(List.copyOf(outcome.truncations()));
            return new AnalysisContribution(Capability.FLOWS, outcome.flows(), diagnostics);
        });
    }

    public List<ExecutionFlow> trace(Map<String, CallGraphNode> callGraph, List<EndpointInfo> endpoints) {
        return trace(callGraph, endpoints, AnalysisProgressListener.NOOP);
    }

    /**
     * 追踪执行流，支持协作取消（O-04）：逐端点与 DFS 每层检查
     * {@code progress.isCancelled()}，取消时抛 {@link JobCancelledException}。
     *
     * <p>体积防护见类注释：单流步数上限 + 全局预算，截断记录经 progress 发
     * WARN 事件并打日志。</p>
     */
    public List<ExecutionFlow> trace(Map<String, CallGraphNode> callGraph, List<EndpointInfo> endpoints,
                                     AnalysisProgressListener progress) {
        return traceWithBudget(callGraph, endpoints, progress).flows();
    }

    TraceOutcome traceWithBudget(Map<String, CallGraphNode> callGraph,
                                 List<EndpointInfo> endpoints,
                                 AnalysisProgressListener progress) {
        List<ExecutionFlow> flows = new ArrayList<>();
        List<String> truncations = new ArrayList<>();
        Budget budget = new Budget(maxTotalSteps, maxStepsPerFlow);

        Set<String> allKeys = callGraph.keySet();

        for (int i = 0; i < endpoints.size(); i++) {
            EndpointInfo ep = endpoints.get(i);
            if (progress.isCancelled()) {
                throw new JobCancelledException("Execution flow tracing cancelled");
            }
            if (budget.exhausted()) {
                long skipped = endpoints.subList(i, endpoints.size()).stream()
                        .filter(rest -> allKeys.contains(
                                MethodKey.nameKey(rest.controllerClass(), rest.controllerMethod())))
                        .count();
                if (skipped > 0) {
                    truncations.add("global step budget (" + budget.maxTotalSteps
                            + ") exhausted; skipped " + skipped + " endpoint flow(s)");
                }
                break;
            }
            String entryKey = MethodKey.nameKey(ep.controllerClass(), ep.controllerMethod());
            if (!allKeys.contains(entryKey)) {
                continue;
            }

            List<FlowStep> steps = new ArrayList<>();
            Set<String> visited = new HashSet<>();
            Set<String> pathNodes = new HashSet<>();
            budget.flowTruncated = false;
            dfs(callGraph, entryKey, 0, visited, pathNodes, steps, budget, progress);

            if (budget.flowTruncated) {
                truncations.add(entryKey + ": truncated at " + steps.size()
                        + " steps (cap " + budget.maxStepsPerFlow + ")");
            }

            int maxDepth = steps.stream().mapToInt(FlowStep::depth).max().orElse(0);
            flows.add(new ExecutionFlow(entryKey, steps, maxDepth));
        }

        if (!truncations.isEmpty()) {
            String summary = String.join("; ", truncations);
            progress.onEvent("analysis", "WARN", "Execution flow tracing truncated: " + summary);
            log.warn("Execution flow tracing truncated: {}", summary);
        }
        return new TraceOutcome(flows, truncations);
    }

    private void dfs(Map<String, CallGraphNode> callGraph, String currentKey,
                     int depth, Set<String> visited, Set<String> pathNodes, List<FlowStep> steps,
                     Budget budget, AnalysisProgressListener progress) {
        if (progress.isCancelled()) {
            throw new JobCancelledException("Execution flow tracing cancelled");
        }
        if (depth > MAX_DEPTH || pathNodes.contains(currentKey)) {
            return;
        }
        if (budget.exhausted()) {
            // 全局预算耗尽：该路径未展开，当前流按截断记。
            budget.flowTruncated = true;
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
                if (steps.size() >= budget.maxStepsPerFlow) {
                    budget.flowTruncated = true;
                    return;
                }
                steps.add(new FlowStep(depth, currentKey, node.className(), node.methodName()));
                budget.remaining--;
            }

            for (CallEdge callee : node.calleeDetails()) {
                String calleeKey = callee.to();
                if (callGraph.containsKey(calleeKey)) {
                    dfs(callGraph, calleeKey, depth + 1, visited, pathNodes, steps, budget, progress);
                } else {
                    // External / unresolved call — record as leaf at next depth
                    if (budget.exhausted() || steps.size() >= budget.maxStepsPerFlow) {
                        budget.flowTruncated = true;
                        return;
                    }
                    String clazz = MethodKey.classNameOf(calleeKey);
                    String method = MethodKey.methodNameOf(calleeKey);
                    steps.add(new FlowStep(depth + 1, calleeKey, clazz, method));
                    budget.remaining--;
                }
            }
        } finally {
            pathNodes.remove(currentKey);
        }
    }

    /** 单次 trace 调用内的可变预算与截断标记（调用栈内使用，非线程共享）。 */
    private static final class Budget {
        final int maxTotalSteps;
        final int maxStepsPerFlow;
        int remaining;
        boolean flowTruncated;

        Budget(int maxTotalSteps, int maxStepsPerFlow) {
            this.maxTotalSteps = maxTotalSteps;
            this.maxStepsPerFlow = maxStepsPerFlow;
            this.remaining = maxTotalSteps;
        }

        boolean exhausted() {
            return remaining <= 0;
        }
    }

    record TraceOutcome(List<ExecutionFlow> flows, List<String> truncations) {}
}
