package com.argus.analyzer.env;

/**
 * Abstract base for Maven execution-related failures.
 * All Maven exceptions carry the {@code commandLine} that triggered the failure.
 */
public abstract class MavenException extends ClasspathException {

    private static final long serialVersionUID = 1L;

    private final String commandLine;

    public MavenException(String message, String commandLine) {
        super(message);
        this.commandLine = commandLine;
    }

    @Override
    public String commandLine() {
        return commandLine;
    }
}
