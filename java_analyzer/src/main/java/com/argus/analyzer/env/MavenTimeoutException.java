package com.argus.analyzer.env;

/**
 * Maven process timed out before completing.
 */
public class MavenTimeoutException extends ClasspathException {

    private final long timeoutSeconds;
    private final String commandLine;

    public MavenTimeoutException(String message, long timeoutSeconds, String commandLine) {
        super(message);
        this.timeoutSeconds = timeoutSeconds;
        this.commandLine = commandLine;
    }

    public long getTimeoutSeconds() {
        return timeoutSeconds;
    }

    public String getCommandLine() {
        return commandLine;
    }
}
