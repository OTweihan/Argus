package com.argus.analyzer.api.dto;

import java.util.List;
import java.util.Map;

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

    private boolean classpathAvailable;
    private int jarCount;
    private String classpathSource;
    private List<String> classpathWarnings;
    private List<String> classpathErrors;
    private String classpathCommand;
    private Integer classpathExitCode;
    private Long classpathDurationMs;
    private String classpathStdoutTail;
    private String classpathStderrTail;
    private boolean classpathTimedOut;

    // P0/P3: Maven 模块信息
    private String rootPom;
    private int moduleCount;
    private int sourceRootCount;
    private List<String> modules;

    // P3: classpath 模块明细
    private List<String> classpathTargetModules;
    private List<String> classpathFailedModules;

    // P4: 模块分类摘要
    private int applicationModuleCount;
    private int businessModuleCount;
    private int libraryModuleCount;
    private int bomModuleCount;
    private java.util.Map<String, String> moduleTypes;

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

    public boolean isClasspathAvailable() { return classpathAvailable; }
    public void setClasspathAvailable(boolean classpathAvailable) { this.classpathAvailable = classpathAvailable; }

    public int getJarCount() { return jarCount; }
    public void setJarCount(int jarCount) { this.jarCount = jarCount; }

    public String getClasspathSource() { return classpathSource; }
    public void setClasspathSource(String classpathSource) { this.classpathSource = classpathSource; }

    public List<String> getClasspathWarnings() { return classpathWarnings; }
    public void setClasspathWarnings(List<String> classpathWarnings) { this.classpathWarnings = classpathWarnings; }

    public List<String> getClasspathErrors() { return classpathErrors; }
    public void setClasspathErrors(List<String> classpathErrors) { this.classpathErrors = classpathErrors; }

    public String getClasspathCommand() { return classpathCommand; }
    public void setClasspathCommand(String classpathCommand) { this.classpathCommand = classpathCommand; }

    public Integer getClasspathExitCode() { return classpathExitCode; }
    public void setClasspathExitCode(Integer classpathExitCode) { this.classpathExitCode = classpathExitCode; }

    public Long getClasspathDurationMs() { return classpathDurationMs; }
    public void setClasspathDurationMs(Long classpathDurationMs) { this.classpathDurationMs = classpathDurationMs; }

    public String getClasspathStdoutTail() { return classpathStdoutTail; }
    public void setClasspathStdoutTail(String classpathStdoutTail) { this.classpathStdoutTail = classpathStdoutTail; }

    public String getClasspathStderrTail() { return classpathStderrTail; }
    public void setClasspathStderrTail(String classpathStderrTail) { this.classpathStderrTail = classpathStderrTail; }

    public boolean isClasspathTimedOut() { return classpathTimedOut; }
    public void setClasspathTimedOut(boolean classpathTimedOut) { this.classpathTimedOut = classpathTimedOut; }

    public String getRootPom() { return rootPom; }
    public void setRootPom(String rootPom) { this.rootPom = rootPom; }

    public int getModuleCount() { return moduleCount; }
    public void setModuleCount(int moduleCount) { this.moduleCount = moduleCount; }

    public int getSourceRootCount() { return sourceRootCount; }
    public void setSourceRootCount(int sourceRootCount) { this.sourceRootCount = sourceRootCount; }

    public List<String> getModules() { return modules; }
    public void setModules(List<String> modules) { this.modules = modules; }

    public List<String> getClasspathTargetModules() { return classpathTargetModules; }
    public void setClasspathTargetModules(List<String> classpathTargetModules) { this.classpathTargetModules = classpathTargetModules; }

    public List<String> getClasspathFailedModules() { return classpathFailedModules; }
    public void setClasspathFailedModules(List<String> classpathFailedModules) { this.classpathFailedModules = classpathFailedModules; }

    public int getApplicationModuleCount() { return applicationModuleCount; }
    public void setApplicationModuleCount(int applicationModuleCount) { this.applicationModuleCount = applicationModuleCount; }

    public int getBusinessModuleCount() { return businessModuleCount; }
    public void setBusinessModuleCount(int businessModuleCount) { this.businessModuleCount = businessModuleCount; }

    public int getLibraryModuleCount() { return libraryModuleCount; }
    public void setLibraryModuleCount(int libraryModuleCount) { this.libraryModuleCount = libraryModuleCount; }

    public int getBomModuleCount() { return bomModuleCount; }
    public void setBomModuleCount(int bomModuleCount) { this.bomModuleCount = bomModuleCount; }

    public Map<String, String> getModuleTypes() { return moduleTypes; }
    public void setModuleTypes(Map<String, String> moduleTypes) { this.moduleTypes = moduleTypes; }
}
