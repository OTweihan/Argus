package com.argus.analyzer.env;

/**
 * Maven process completed with a non-zero exit code.
 */
public class MavenExecutionException extends MavenException {

    private static final long serialVersionUID = 1L;

    private final int exitCode;
    private final String stderrTail;
    private final long durationMs;
    private final String stdoutTail;

    public MavenExecutionException(String message, int exitCode, String commandLine,
                                    String stderrTail, long durationMs, String stdoutTail) {
        super(message, commandLine);
        this.exitCode = exitCode;
        this.stderrTail = stderrTail;
        this.durationMs = durationMs;
        this.stdoutTail = stdoutTail;
    }

    @Override
    public Integer exitCode() {
        return exitCode;
    }

    @Override
    public String stderrTail() {
        return stderrTail;
    }

    @Override
    public long durationMs() {
        return durationMs;
    }

    @Override
    public String stdoutTail() {
        return stdoutTail;
    }
}
