package com.argus.analyzer.domain.model;

public record FindingItem(
    String ruleId,
    String severity,
    String title,
    String description,
    String filePath,
    int lineNumber,
    String snippet,
    String ruleCategory,
    String analysisConfidence
) {}
