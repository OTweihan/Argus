package com.argus.analyzer.domain.model;

import java.util.List;

public record ExecutionFlow(String entryPoint, List<FlowStep> steps, int callDepth) {}
