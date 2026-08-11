package com.argus.analyzer.domain.model;

import java.util.List;

public record CallEdge(
    String to,
    String methodName,
    String typeName,
    ResolutionType resolutionType,
    Confidence confidence,
    List<String> candidates,
    String sourceFile,
    int line
) {}
