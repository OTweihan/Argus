package com.argus.analyzer.env;

/**
 * Maven executable not found after exhausting the 8-step detection chain.
 */
public class MavenNotFoundException extends ClasspathException {

    public MavenNotFoundException(String message) {
        super(message);
    }
}
