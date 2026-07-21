package com.argus.analyzer.api.dto;

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
