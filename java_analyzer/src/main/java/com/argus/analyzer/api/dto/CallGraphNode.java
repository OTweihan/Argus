package com.argus.analyzer.api.dto;

import java.util.List;

public class CallGraphNode {

    private String className;
    private String methodName;
    private String methodSignature;
    private List<String> callees;

    public CallGraphNode() {}

    public CallGraphNode(String className, String methodName, String methodSignature, List<String> callees) {
        this.className = className;
        this.methodName = methodName;
        this.methodSignature = methodSignature;
        this.callees = callees;
    }

    public String getClassName() { return className; }
    public void setClassName(String className) { this.className = className; }

    public String getMethodName() { return methodName; }
    public void setMethodName(String methodName) { this.methodName = methodName; }

    public String getMethodSignature() { return methodSignature; }
    public void setMethodSignature(String methodSignature) { this.methodSignature = methodSignature; }

    public List<String> getCallees() { return callees; }
    public void setCallees(List<String> callees) { this.callees = callees; }
}
