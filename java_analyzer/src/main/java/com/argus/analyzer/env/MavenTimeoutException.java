package com.argus.analyzer.env;

/**
 * Maven process timed out before completing.
 */
public class MavenTimeoutException extends MavenException {

    private static final long serialVersionUID = 1L;

    private final long timeoutSeconds;
    private final long durationMs;
    private final String stdoutTail;
    private final String stderrTail;

    public MavenTimeoutException(String message, long timeoutSeconds, String commandLine,
                                  long durationMs, String stdoutTail, String stderrTail) {
        super(message, commandLine);
        this.timeoutSeconds = timeoutSeconds;
        this.durationMs = durationMs;
        this.stdoutTail = stdoutTail;
        this.stderrTail = stderrTail;
    }

    public long timeoutSeconds() {
        return timeoutSeconds;
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

    @Override
    public boolean timedOut() {
        return true;
    }
}
