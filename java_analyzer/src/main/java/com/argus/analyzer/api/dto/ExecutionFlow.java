package com.argus.analyzer.api.dto;

import java.util.List;

public class ExecutionFlow {

    private String entryPoint;
    private List<FlowStep> steps;
    private int callDepth;

    public ExecutionFlow() {}

    public ExecutionFlow(String entryPoint, List<FlowStep> steps, int callDepth) {
        this.entryPoint = entryPoint;
        this.steps = steps;
        this.callDepth = callDepth;
    }

    public String getEntryPoint() { return entryPoint; }
    public void setEntryPoint(String entryPoint) { this.entryPoint = entryPoint; }

    public List<FlowStep> getSteps() { return steps; }
    public void setSteps(List<FlowStep> steps) { this.steps = steps; }

    public int getCallDepth() { return callDepth; }
    public void setCallDepth(int callDepth) { this.callDepth = callDepth; }
}
