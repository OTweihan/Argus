package com.argus.analyzer.env;

/**
 * Maven executable not found after exhausting the detection chain.
 */
public class MavenNotFoundException extends MavenException {

    private static final long serialVersionUID = 1L;

    public MavenNotFoundException(String message, String commandLine) {
        super(message, commandLine);
    }
}
