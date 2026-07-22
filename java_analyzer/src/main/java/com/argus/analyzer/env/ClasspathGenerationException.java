package com.argus.analyzer.env;

/**
 * Classpath file generation failed — Maven ran but did not produce the expected output file,
 * or infrastructure issues (I/O errors) prevented execution.
 *
 * <p>Three constructor shapes match three failure scenarios:
 * <ul>
 *   <li><b>No execution context</b> — e.g. directory creation failed</li>
 *   <li><b>No execution context + cause</b> — e.g. IOException during process launch</li>
 *   <li><b>Full execution context</b> — Maven ran but the classpath file was missing</li>
 * </ul>
 */
public class ClasspathGenerationException extends ClasspathException {

    private static final long serialVersionUID = 1L;

    private final String commandLine;
    private final Integer exitCode;
    private final long durationMs;
    private final String stdoutTail;
    private final String stderrTail;

    /** No execution context (e.g. directory creation failure). */
    public ClasspathGenerationException(String message) {
        super(message);
        this.commandLine = null;
        this.exitCode = null;
        this.durationMs = -1;
        this.stdoutTail = null;
        this.stderrTail = null;
    }

    /** No execution context + cause (e.g. IOException during process launch). */
    public ClasspathGenerationException(String message, Throwable cause) {
        super(message, cause);
        this.commandLine = null;
        this.exitCode = null;
        this.durationMs = -1;
        this.stdoutTail = null;
        this.stderrTail = null;
    }

    /** Full execution context (Maven executed but the classpath file was not created). */
    public ClasspathGenerationException(String message, String commandLine, Integer exitCode,
                                         long durationMs, String stdoutTail, String stderrTail) {
        super(message);
        this.commandLine = commandLine;
        this.exitCode = exitCode;
        this.durationMs = durationMs;
        this.stdoutTail = stdoutTail;
        this.stderrTail = stderrTail;
    }

    @Override
    public String commandLine() {
        return commandLine;
    }

    @Override
    public Integer exitCode() {
        return exitCode;
    }

    @Override
    public long durationMs() {
        return durationMs;
    }

    @Override
    public String stdoutTail() {
        return stdoutTail;
    }

    @Override
    public String stderrTail() {
        return stderrTail;
    }
}
