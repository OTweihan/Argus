package com.argus.analyzer.env;

import java.nio.file.Path;
import java.util.Collections;
import java.util.List;

public class ClasspathResult {

    private boolean available;
    private boolean generated;
    private boolean fallback;
    private List<String> jars;
    private String source;
    private List<String> warnings;
    private List<String> errors;
    private String command;
    private Integer exitCode;
    private Long durationMs;
    private String stdoutTail;
    private String stderrTail;
    private boolean timedOut;

    public ClasspathResult() {}

    public ClasspathResult(boolean available, boolean generated, boolean fallback,
                           List<String> jars, String source,
                           List<String> warnings, List<String> errors,
                           String command, Integer exitCode) {
        this.available = available;
        this.generated = generated;
        this.fallback = fallback;
        this.jars = jars != null ? jars : Collections.emptyList();
        this.source = source;
        this.warnings = warnings != null ? warnings : Collections.emptyList();
        this.errors = errors != null ? errors : Collections.emptyList();
        this.command = command;
        this.exitCode = exitCode;
    }

    public static ClasspathResult unavailable(String reason) {
        return new ClasspathResult(false, false, true, List.of(), "none",
                List.of(reason), List.of(reason), null, null);
    }

    public static ClasspathResult fromJars(List<Path> jarPaths, String source) {
        List<String> jarStrs = jarPaths.stream()
                .map(Path::toString)
                .toList();
        return new ClasspathResult(true, false, false, jarStrs, source,
                List.of(), List.of(), null, null);
    }

    public boolean isAvailable() { return available; }
    public void setAvailable(boolean available) { this.available = available; }

    public boolean isGenerated() { return generated; }
    public void setGenerated(boolean generated) { this.generated = generated; }

    public boolean isFallback() { return fallback; }
    public void setFallback(boolean fallback) { this.fallback = fallback; }

    public List<String> getJars() { return jars; }
    public void setJars(List<String> jars) { this.jars = jars; }

    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }

    public List<String> getWarnings() { return warnings; }
    public void setWarnings(List<String> warnings) { this.warnings = warnings; }

    public List<String> getErrors() { return errors; }
    public void setErrors(List<String> errors) { this.errors = errors; }

    public String getCommand() { return command; }
    public void setCommand(String command) { this.command = command; }

    public Integer getExitCode() { return exitCode; }
    public void setExitCode(Integer exitCode) { this.exitCode = exitCode; }

    public Long getDurationMs() { return durationMs; }
    public void setDurationMs(Long durationMs) { this.durationMs = durationMs; }

    public String getStdoutTail() { return stdoutTail; }
    public void setStdoutTail(String stdoutTail) { this.stdoutTail = stdoutTail; }

    public String getStderrTail() { return stderrTail; }
    public void setStderrTail(String stderrTail) { this.stderrTail = stderrTail; }

    public boolean isTimedOut() { return timedOut; }
    public void setTimedOut(boolean timedOut) { this.timedOut = timedOut; }

    public void copyExecutionDiagnosticsFrom(ClasspathResult other) {
        if (other == null) {
            return;
        }
        this.command = other.command;
        this.exitCode = other.exitCode;
        this.durationMs = other.durationMs;
        this.stdoutTail = other.stdoutTail;
        this.stderrTail = other.stderrTail;
        this.timedOut = other.timedOut;
    }

    /** 是否有至少一个有效的 JAR 路径（文件存在于磁盘上）。 */
    public boolean hasValidJars() {
        return jars != null && !jars.isEmpty();
    }

    /** Adds a warning, ensuring the warnings list is mutable. */
    public void addWarning(String warning) {
        if (warnings == null) {
            warnings = new java.util.ArrayList<>();
        }
        warnings.add(warning);
    }
}
