package com.argus.analyzer.api.dto;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public record ClusterInfo(
    String clusterId,
    String suggestedLabel,
    List<String> memberKeys,
    int memberCount
) {
    public ClusterInfo {
        // 防御性拷贝，保证真正的不可变性
        // 使用 unmodifiableList 而非 List.copyOf()，兼容 null 元素场景
        memberKeys = memberKeys == null
            ? List.of()
            : Collections.unmodifiableList(new ArrayList<>(memberKeys));
        memberCount = memberKeys.size();
    }

    public ClusterInfo(String clusterId, String suggestedLabel, List<String> memberKeys) {
        this(clusterId, suggestedLabel, memberKeys, 0);
    }
}
