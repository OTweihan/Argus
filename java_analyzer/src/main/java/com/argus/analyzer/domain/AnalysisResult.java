package com.argus.analyzer.domain;

import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.ClusterInfo;
import com.argus.analyzer.domain.model.EndpointInfo;
import com.argus.analyzer.domain.model.ExecutionFlow;
import com.argus.analyzer.domain.model.FindingItem;

import java.util.List;
import java.util.Map;

/**
 * 一次分析的不可变结果（O-11）。
 *
 * <p>分析核心的产出；HTTP adapter 最后把它映射为 wire DTO
 * {@code api.dto.AnalyzeResponse}（两者字段同构，但核心不依赖 HTTP 层）。</p>
 */
public record AnalysisResult(
        List<EndpointInfo> endpoints,
        Map<String, CallGraphNode> callGraph,
        List<FindingItem> findings,
        List<ExecutionFlow> executionFlows,
        List<ClusterInfo> clusters,
        AnalyzerDiagnostics diagnostics
) {}
