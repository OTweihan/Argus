package com.argus.analyzer.env;

/**
 * Base exception for classpath resolution failures.
 */
public class ClasspathException extends RuntimeException {

    public ClasspathException(String message) {
        super(message);
    }

    public ClasspathException(String message, Throwable cause) {
        super(message, cause);
    }
}
