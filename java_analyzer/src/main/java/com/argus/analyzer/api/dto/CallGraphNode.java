package com.argus.analyzer.api.dto;

import java.util.List;

public record CallGraphNode(
    String className,
    String methodName,
    String methodSignature,
    List<CallEdge> calleeDetails
) {}
