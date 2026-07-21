package com.argus.analyzer.env;

/**
 * Maven process completed with a non-zero exit code.
 */
public class MavenExecutionException extends ClasspathException {

    private final int exitCode;
    private final String commandLine;
    private final String outputTail;

    public MavenExecutionException(String message, int exitCode, String commandLine, String outputTail) {
        super(message);
        this.exitCode = exitCode;
        this.commandLine = commandLine;
        this.outputTail = outputTail;
    }

    public int getExitCode() {
        return exitCode;
    }

    public String getCommandLine() {
        return commandLine;
    }

    public String getOutputTail() {
        return outputTail;
    }
}
