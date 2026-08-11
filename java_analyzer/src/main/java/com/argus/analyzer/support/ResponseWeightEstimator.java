package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.api.dto.AnalyzerDiagnostics;
import com.argus.analyzer.api.dto.CallEdge;
import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.ClusterInfo;
import com.argus.analyzer.api.dto.EndpointInfo;
import com.argus.analyzer.api.dto.ExecutionFlow;
import com.argus.analyzer.api.dto.FindingItem;
import com.argus.analyzer.api.dto.FlowStep;
import com.argus.analyzer.api.dto.ParseFailureDetail;

import java.util.List;
import java.util.Map;

/**
 * {@link AnalyzeResponse} 的近似堆内存权重估算（O-08）。
 *
 * <p>目标是给 {@link ProjectIndexCache} 提供"每条目估算占用字节"，用于按权重淘汰与
 * 超大条目旁路，而不是精确的 JVM 内存度量。估算基于字符串长度（Java 17+ compact
 * strings 下 Latin-1 为 1 字节/字符、UTF-16 为 2 字节/字符，这里保守按 2 字节/字符）
 * 加固定的对象头/集合槽位开销，全程零分配、O(响应元素数)。</p>
 *
 * <p>估算偏差只影响缓存命中率，不影响分析结果正确性：高估导致缓存更早淘汰（更多重复
 * 分析），低估导致实际堆占用略超预算——因此常量按偏保守（偏高）方向取值。</p>
 */
public final class ResponseWeightEstimator {

    private ResponseWeightEstimator() {}

    // 每个记录/对象头的固定开销（对象头 + 引用字段），字节。
    private static final long OBJECT_OVERHEAD = 64;
    // String 对象头 + 底层 char[] 头开销（不含字符内容）。
    private static final long STRING_OVERHEAD = 40;
    // 集合中每个元素对应的槽位/节点开销（ArrayList 引用槽、Map 节点等）。
    private static final long SLOT_OVERHEAD = 24;

    /** 估算 {@link AnalyzeResponse} 的近似保留堆字节数。 */
    public static long estimateWeight(AnalyzeResponse response) {
        if (response == null) return 0;
        return OBJECT_OVERHEAD
                + weightOf(response.endpoints())
                + weightOf(response.callGraph())
                + weightOf(response.findings())
                + weightOf(response.executionFlows())
                + weightOf(response.clusters())
                + weightOf(response.diagnostics());
    }

    private static long weightOf(List<EndpointInfo> endpoints) {
        long weight = listOverhead(endpoints);
        if (endpoints == null) return weight;
        for (EndpointInfo endpoint : endpoints) {
            if (endpoint == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(endpoint.path())
                    + str(endpoint.httpMethod())
                    + str(endpoint.controllerClass())
                    + str(endpoint.controllerMethod())
                    + str(endpoint.returnType())
                    + listOverhead(endpoint.parameters())
                    + strings(endpoint.parameters());
        }
        return weight;
    }

    private static long weightOf(Map<String, CallGraphNode> callGraph) {
        long weight = mapOverhead(callGraph);
        if (callGraph == null) return weight;
        for (Map.Entry<String, CallGraphNode> entry : callGraph.entrySet()) {
            // 节点键是完整方法签名，单独计入。
            weight += str(entry.getKey());
            CallGraphNode node = entry.getValue();
            if (node == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(node.className())
                    + str(node.methodName())
                    + str(node.methodSignature())
                    + weightOf(node.calleeDetails());
        }
        return weight;
    }

    private static long weightOf(List<CallEdge> edges) {
        long weight = listOverhead(edges);
        if (edges == null) return weight;
        for (CallEdge edge : edges) {
            if (edge == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(edge.to())
                    + str(edge.methodName())
                    + str(edge.typeName())
                    + str(edge.sourceFile())
                    // resolutionType / confidence 枚举 + line 字段
                    + 16
                    + listOverhead(edge.candidates())
                    + strings(edge.candidates());
        }
        return weight;
    }

    private static long weightOf(List<FindingItem> findings) {
        long weight = listOverhead(findings);
        if (findings == null) return weight;
        for (FindingItem finding : findings) {
            if (finding == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(finding.ruleId())
                    + str(finding.severity())
                    + str(finding.title())
                    + str(finding.description())
                    + str(finding.filePath())
                    + str(finding.snippet())
                    + str(finding.ruleCategory())
                    + str(finding.analysisConfidence())
                    // int lineNumber
                    + 8;
        }
        return weight;
    }

    private static long weightOf(List<ExecutionFlow> flows) {
        long weight = listOverhead(flows);
        if (flows == null) return weight;
        for (ExecutionFlow flow : flows) {
            if (flow == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(flow.entryPoint())
                    // int callDepth
                    + 8;
            List<FlowStep> steps = flow.steps();
            weight += listOverhead(steps);
            if (steps == null) continue;
            for (FlowStep step : steps) {
                if (step == null) continue;
                weight += OBJECT_OVERHEAD
                        // int depth
                        + 8
                        + str(step.methodKey())
                        + str(step.className())
                        + str(step.methodName());
            }
        }
        return weight;
    }

    private static long weightOf(List<ClusterInfo> clusters) {
        long weight = listOverhead(clusters);
        if (clusters == null) return weight;
        for (ClusterInfo cluster : clusters) {
            if (cluster == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(cluster.clusterId())
                    + str(cluster.suggestedLabel())
                    + listOverhead(cluster.memberKeys())
                    + strings(cluster.memberKeys());
        }
        return weight;
    }

    private static long weightOf(AnalyzerDiagnostics diagnostics) {
        if (diagnostics == null) return 0;
        // 可变对象：对象头 + 约 20 个基础类型字段。
        long weight = OBJECT_OVERHEAD * 2 + 160;
        weight += str(diagnostics.getClasspathSource())
                + str(diagnostics.getClasspathCommand())
                + str(diagnostics.getClasspathStdoutTail())
                + str(diagnostics.getClasspathStderrTail())
                + str(diagnostics.getRootPom());
        weight += listOverhead(diagnostics.getFailedFiles())
                + failedFiles(diagnostics.getFailedFiles());
        weight += listOverhead(diagnostics.getClasspathWarnings())
                + strings(diagnostics.getClasspathWarnings());
        weight += listOverhead(diagnostics.getClasspathErrors())
                + strings(diagnostics.getClasspathErrors());
        weight += listOverhead(diagnostics.getModules())
                + strings(diagnostics.getModules());
        weight += listOverhead(diagnostics.getClasspathTargetModules())
                + strings(diagnostics.getClasspathTargetModules());
        weight += listOverhead(diagnostics.getClasspathFailedModules())
                + strings(diagnostics.getClasspathFailedModules());
        weight += mapOverhead(diagnostics.getModuleTypes());
        if (diagnostics.getModuleTypes() != null) {
            for (Map.Entry<String, String> entry : diagnostics.getModuleTypes().entrySet()) {
                weight += str(entry.getKey()) + str(entry.getValue());
            }
        }
        return weight;
    }

    private static long failedFiles(List<ParseFailureDetail> details) {
        if (details == null) return 0;
        long weight = 0;
        for (ParseFailureDetail detail : details) {
            if (detail == null) continue;
            weight += OBJECT_OVERHEAD
                    + str(detail.file())
                    + listOverhead(detail.problems())
                    + strings(detail.problems());
        }
        return weight;
    }

    private static long str(String value) {
        if (value == null) return 0;
        return STRING_OVERHEAD + 2L * value.length();
    }

    private static long strings(List<String> values) {
        if (values == null) return 0;
        long weight = 0;
        for (String value : values) {
            weight += str(value);
        }
        return weight;
    }

    private static long listOverhead(List<?> list) {
        return list == null ? 0 : SLOT_OVERHEAD * list.size();
    }

    private static long mapOverhead(Map<?, ?> map) {
        return map == null ? 0 : SLOT_OVERHEAD * 2L * map.size();
    }
}
