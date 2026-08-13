package com.argus.analyzer.domain.model;

public enum Confidence {
    HIGH,
    MEDIUM,
    // 保留用于 wire 契约（call graph 边 confidence 字段）与未来调用解析降级；
    // 当前 CallGraphBuilder 不产出 LOW（见其注释），但删除会破坏序列化兼容。
    LOW,
    UNKNOWN
}
