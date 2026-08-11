package com.argus.analyzer.domain.model;

import java.util.List;

public record CallGraphNode(
    String className,
    String methodName,
    String methodSignature,
    List<CallEdge> calleeDetails
) {}
