package com.argus.analyzer.api.dto;

import java.util.List;

public record ExecutionFlow(String entryPoint, List<FlowStep> steps, int callDepth) {}
