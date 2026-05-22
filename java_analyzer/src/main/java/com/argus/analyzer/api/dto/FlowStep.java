package com.argus.analyzer.api.dto;

public class FlowStep {

    private int depth;
    private String methodKey;
    private String className;
    private String methodName;

    public FlowStep() {}

    public FlowStep(int depth, String methodKey, String className, String methodName) {
        this.depth = depth;
        this.methodKey = methodKey;
        this.className = className;
        this.methodName = methodName;
    }

    public int getDepth() { return depth; }
    public void setDepth(int depth) { this.depth = depth; }

    public String getMethodKey() { return methodKey; }
    public void setMethodKey(String methodKey) { this.methodKey = methodKey; }

    public String getClassName() { return className; }
    public void setClassName(String className) { this.className = className; }

    public String getMethodName() { return methodName; }
    public void setMethodName(String methodName) { this.methodName = methodName; }
}
