package com.argus.analyzer.env;

/**
 * Classpath file generation failed — Maven ran but did not produce the expected output file.
 */
public class ClasspathGenerationException extends ClasspathException {

    public ClasspathGenerationException(String message) {
        super(message);
    }

    public ClasspathGenerationException(String message, Throwable cause) {
        super(message, cause);
    }
}
