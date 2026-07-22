package com.argus.analyzer.env;

/**
 * Base exception for classpath resolution failures.
 * Provides a unified diagnostic interface so callers can extract
 * execution context without switching on concrete subtypes.
 */
public abstract class ClasspathException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public ClasspathException(String message) {
        super(message);
    }

    public ClasspathException(String message, Throwable cause) {
        super(message, cause);
    }

    /** @return command line that produced this error, or null if not available */
    public String commandLine() { return null; }

    /** @return process exit code, or null if the process never ran */
    public Integer exitCode() { return null; }

    /** @return wall-clock duration in ms, or -1 if execution never started */
    public long durationMs() { return -1; }

    /** @return last N chars of stdout, or null */
    public String stdoutTail() { return null; }

    /** @return last N chars of stderr, or null */
    public String stderrTail() { return null; }

    /** @return true iff the failure was caused by timeout */
    public boolean timedOut() { return false; }
}
