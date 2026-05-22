package com.argus.analyzer.support;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class SourceLocator {

    private static final Logger log = LoggerFactory.getLogger(SourceLocator.class);

    public Path resolve(String sourcePath) {
        Path path = Paths.get(sourcePath).toAbsolutePath().normalize();

        if (!Files.exists(path)) {
            throw new IllegalArgumentException("Source path does not exist: " + path);
        }
        if (!Files.isDirectory(path)) {
            throw new IllegalArgumentException("Source path is not a directory: " + path);
        }

        log.info("Resolved source path: {}", path);
        return path;
    }
}
