package com.argus.analyzer.env.classpath.parser;

import com.argus.analyzer.env.ClasspathResult;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * Parses a classpath text file into a {@link ClasspathResult}.
 * Handles both Windows ({@code ;}) and Unix ({@code :}) separators,
 * and verifies each JAR path exists on disk.
 *
 * <p>Stateless utility — not a Spring bean.
 */
public final class ClasspathFileReader {

    public ClasspathResult read(Path classpathFile, String source) {
        try {
            String content = Files.readString(classpathFile, StandardCharsets.UTF_8).trim();
            if (content.isEmpty()) {
                return new ClasspathResult(false, false, true, List.of(), source,
                        List.of("Classpath file is empty: " + classpathFile),
                        List.of(), null, null);
            }

            String separator = content.contains(";") ? ";" : ":";
            String[] parts = content.split(separator);
            List<String> validJars = new ArrayList<>();
            List<String> warnings = new ArrayList<>();

            for (String part : parts) {
                String jarPath = part.trim();
                if (jarPath.isEmpty()) {
                    continue;
                }
                if (Files.exists(Paths.get(jarPath))) {
                    validJars.add(jarPath);
                } else {
                    warnings.add("JAR not found, skipping: " + jarPath);
                }
            }

            return new ClasspathResult(true, false, false, validJars, source,
                    warnings, List.of(), null, null);

        } catch (IOException e) {
            return new ClasspathResult(false, false, true, List.of(), source,
                    List.of("Failed to read classpath file: " + e.getMessage()),
                    List.of(e.getMessage()), null, null);
        }
    }
}
