package com.argus.analyzer.api.dto;

import java.util.List;

public class AnalyzerDiagnostics {

    private int totalSourceFiles;
    private int parsedFileCount;
    private int failedFileCount;
    private List<ParseFailureDetail> failedFiles;

    private int totalCalls;
    private int resolvedHigh;
    private int resolvedMedium;
    private int resolvedLow;
    private int unresolved;

    public AnalyzerDiagnostics() {}

    public AnalyzerDiagnostics(int totalSourceFiles, int parsedFileCount, int failedFileCount,
                               List<ParseFailureDetail> failedFiles,
                               int totalCalls, int resolvedHigh, int resolvedMedium,
                               int resolvedLow, int unresolved) {
        this.totalSourceFiles = totalSourceFiles;
        this.parsedFileCount = parsedFileCount;
        this.failedFileCount = failedFileCount;
        this.failedFiles = failedFiles;
        this.totalCalls = totalCalls;
        this.resolvedHigh = resolvedHigh;
        this.resolvedMedium = resolvedMedium;
        this.resolvedLow = resolvedLow;
        this.unresolved = unresolved;
    }

    public int getTotalSourceFiles() { return totalSourceFiles; }
    public void setTotalSourceFiles(int totalSourceFiles) { this.totalSourceFiles = totalSourceFiles; }

    public int getParsedFileCount() { return parsedFileCount; }
    public void setParsedFileCount(int parsedFileCount) { this.parsedFileCount = parsedFileCount; }

    public int getFailedFileCount() { return failedFileCount; }
    public void setFailedFileCount(int failedFileCount) { this.failedFileCount = failedFileCount; }

    public List<ParseFailureDetail> getFailedFiles() { return failedFiles; }
    public void setFailedFiles(List<ParseFailureDetail> failedFiles) { this.failedFiles = failedFiles; }

    public int getTotalCalls() { return totalCalls; }
    public void setTotalCalls(int totalCalls) { this.totalCalls = totalCalls; }

    public int getResolvedHigh() { return resolvedHigh; }
    public void setResolvedHigh(int resolvedHigh) { this.resolvedHigh = resolvedHigh; }

    public int getResolvedMedium() { return resolvedMedium; }
    public void setResolvedMedium(int resolvedMedium) { this.resolvedMedium = resolvedMedium; }

    public int getResolvedLow() { return resolvedLow; }
    public void setResolvedLow(int resolvedLow) { this.resolvedLow = resolvedLow; }

    public int getUnresolved() { return unresolved; }
    public void setUnresolved(int unresolved) { this.unresolved = unresolved; }
}
