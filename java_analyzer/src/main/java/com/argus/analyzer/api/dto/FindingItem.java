package com.argus.analyzer.api.dto;

public record FindingItem(
    String ruleId,
    String severity,
    String title,
    String description,
    String filePath,
    int lineNumber,
    String snippet
) {}
