package com.argus.analyzer.domain;

import java.util.Set;

/**
 * 分析范围（O-11）。HTTP `scope` 字符串只在 adapter 映射为类型化枚举，
 * 核心代码禁止再比较 {@code "all"}、{@code "flows"} 等字符串。
 */
public enum AnalysisScope {

    ALL("all"),
    ENDPOINTS("endpoints"),
    CALLGRAPH("callgraph"),
    FLOWS("flows"),
    CLUSTERS("clusters"),
    MODULES("modules"),
    CHANGED("changed");

    private final String wireValue;

    AnalysisScope(String wireValue) {
        this.wireValue = wireValue;
    }

    /** 兼容输入 wire 值（缓存键/幂等指纹使用）。 */
    public String wireValue() {
        return wireValue;
    }

    /**
     * 从 HTTP/兼容输入 scope 字符串解析。
     *
     * <p>精确匹配旧 Java 行为（大小写敏感）：{@code null} 视为 {@code ALL}
     * （AnalyzeRequest 规范构造把 {@code null} 归一为 {@code "all"}）；
     * 未知/空字符串保守回退 {@link #MODULES}——仅模块/classpath 上下文与诊断，
     * 不运行任何分析 pass（与旧实现下未知 scope 产生空结果的语义一致）。</p>
     */
    public static AnalysisScope from(String value) {
        if (value == null) {
            return ALL;
        }
        return switch (value) {
            case "all" -> ALL;
            case "endpoints" -> ENDPOINTS;
            case "callgraph" -> CALLGRAPH;
            case "flows" -> FLOWS;
            case "clusters" -> CLUSTERS;
            case "modules" -> MODULES;
            case "changed" -> CHANGED;
            default -> MODULES;
        };
    }

    /** 该 scope 下启用的能力集合（决定 AnalysisPlan 选择哪些 pass）。 */
    public Set<Capability> enabledCapabilities() {
        return switch (this) {
            case ALL -> Set.of(Capability.ENDPOINTS, Capability.CALL_GRAPH,
                    Capability.FINDINGS, Capability.FLOWS, Capability.CLUSTERS);
            case ENDPOINTS -> Set.of(Capability.ENDPOINTS);
            case CALLGRAPH -> Set.of(Capability.CALL_GRAPH);
            case FLOWS -> Set.of(Capability.ENDPOINTS, Capability.CALL_GRAPH, Capability.FLOWS);
            case CLUSTERS -> Set.of(Capability.CALL_GRAPH, Capability.CLUSTERS);
            case MODULES, CHANGED -> Set.of();
        };
    }
}
