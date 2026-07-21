package com.argus.analyzer.env.classpath.maven;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;

/**
 * Runs {@code mvn --version} to determine Maven major version.
 * Plain class (not a Spring bean) — stateless, no lifecycle dependencies.
 */
final class MavenVersionChecker {

    private static final Logger log = LoggerFactory.getLogger(MavenVersionChecker.class);

    /**
     * Checks whether the given Maven executable is a 3.x version.
     */
    boolean isMaven3x(String executable) {
        String version = getMavenVersion(executable);
        if (version == null) {
            return false;
        }
        if (!version.startsWith("3.")) {
            log.info("Maven version {} detected at {}, searching for 3.x", version, executable);
            return false;
        }
        return true;
    }

    /**
     * Runs {@code mvn --version} and parses the version string.
     *
     * @return version like {@code "3.8.8"}, or {@code null} if parsing fails
     */
    String getMavenVersion(String executable) {
        try {
            ProcessBuilder pb = new ProcessBuilder(executable, "--version");
            Process process = pb.start();
            boolean finished = process.waitFor(10, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                return null;
            }
            String output = readStream(process.getInputStream());
            for (String line : output.split("\n")) {
                line = line.trim();
                if (line.startsWith("Apache Maven ")) {
                    String rest = line.substring("Apache Maven ".length()).trim();
                    int space = rest.indexOf(' ');
                    return space > 0 ? rest.substring(0, space) : rest;
                }
            }
            return null;
        } catch (Exception e) {
            log.debug("Failed to get Maven version for {}: {}", executable, e.getMessage());
            return null;
        }
    }

    private String readStream(InputStream stream) {
        try (java.io.BufferedReader reader = new java.io.BufferedReader(
                new java.io.InputStreamReader(stream, java.nio.charset.StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                if (!sb.isEmpty()) {
                    sb.append("\n");
                }
                sb.append(line);
            }
            return sb.toString();
        } catch (IOException e) {
            return "";
        }
    }
}
