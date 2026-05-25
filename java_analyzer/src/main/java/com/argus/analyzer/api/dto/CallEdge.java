package com.argus.analyzer.api.dto;

import java.util.List;

public class CallEdge {

    private String to;
    private String methodName;
    private String typeName;
    private ResolutionType resolutionType;
    private Confidence confidence;
    private List<String> candidates;
    private String sourceFile;
    private int line;

    public CallEdge() {}

    public CallEdge(String to, String methodName, String typeName,
                    ResolutionType resolutionType, Confidence confidence,
                    List<String> candidates, String sourceFile, int line) {
        this.to = to;
        this.methodName = methodName;
        this.typeName = typeName;
        this.resolutionType = resolutionType;
        this.confidence = confidence;
        this.candidates = candidates;
        this.sourceFile = sourceFile;
        this.line = line;
    }

    public String getTo() { return to; }
    public void setTo(String to) { this.to = to; }

    public String getMethodName() { return methodName; }
    public void setMethodName(String methodName) { this.methodName = methodName; }

    public String getTypeName() { return typeName; }
    public void setTypeName(String typeName) { this.typeName = typeName; }

    public ResolutionType getResolutionType() { return resolutionType; }
    public void setResolutionType(ResolutionType resolutionType) { this.resolutionType = resolutionType; }

    public Confidence getConfidence() { return confidence; }
    public void setConfidence(Confidence confidence) { this.confidence = confidence; }

    public List<String> getCandidates() { return candidates; }
    public void setCandidates(List<String> candidates) { this.candidates = candidates; }

    public String getSourceFile() { return sourceFile; }
    public void setSourceFile(String sourceFile) { this.sourceFile = sourceFile; }

    public int getLine() { return line; }
    public void setLine(int line) { this.line = line; }
}
