package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.MavenConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Objects;
import java.util.stream.Stream;

/**
 * Locates a Maven 3.x executable via an 8-step priority chain:
 *
 * <ol>
 *   <li>{@code mvnw.cmd} (project-local wrapper, Windows)</li>
 *   <li>{@code mvnw} (project-local wrapper, Unix)</li>
 *   <li>User-specified {@code config.executable}</li>
 *   <li>{@code MAVEN_HOME} — with sibling fallback to 3.x if home points to 4.x</li>
 *   <li>{@code M2_HOME} — with sibling fallback to 3.x if home points to 4.x</li>
 *   <li>{@code MAVEN_HOME} sibling rescan (if not already done)</li>
 *   <li>{@code PATH} — {@code mvn.cmd} / {@code mvn}, prefer 3.x</li>
 *   <li>{@code MAVEN_HOME} last-resort (even if 4.x)</li>
 * </ol>
 *
 * <p>Pure filesystem operations — delegates version checking to {@link MavenVersionChecker}.
 */
@Component
public class MavenDetector {

    private static final Logger log = LoggerFactory.getLogger(MavenDetector.class);

    private final MavenVersionChecker versionChecker;

    /** Spring default constructor. */
    public MavenDetector() {
        this(new MavenVersionChecker());
    }

    /** Test constructor — allows injection of a mock {@link MavenVersionChecker}. */
    public MavenDetector(MavenVersionChecker versionChecker) {
        this.versionChecker = versionChecker;
    }

    /**
     * Returns the absolute path to a Maven 3.x executable, or {@code null} if none found.
     */
    public String detect(Path sourcePath, MavenConfig config) {
        // 1. Project-local wrapper: mvnw.cmd
        Path mvnwCmd = sourcePath.resolve("mvnw.cmd");
        if (Files.exists(mvnwCmd) && Files.isRegularFile(mvnwCmd)) {
            String candidate = mvnwCmd.toAbsolutePath().toString();
            if (versionChecker.isMaven3x(candidate)) {
                return candidate;
            }
            log.warn("mvnw.cmd uses Maven 4+, skipped");
        }

        // 2. Project-local wrapper: mvnw
        Path mvnw = sourcePath.resolve("mvnw");
        if (Files.exists(mvnw) && Files.isRegularFile(mvnw)) {
            String candidate = mvnw.toAbsolutePath().toString();
            if (versionChecker.isMaven3x(candidate)) {
                return candidate;
            }
            log.warn("mvnw uses Maven 4+, skipped");
        }

        // 3. User-specified executable
        if (config.getExecutable() != null && !config.getExecutable().isEmpty()) {
            return config.getExecutable();
        }

        // 4. MAVEN_HOME — with sibling scan if pointing to 4.x
        String mavenHome = getEnv("MAVEN_HOME");
        if (mavenHome != null) {
            String candidate = findMvnInDir(Paths.get(mavenHome));
            if (candidate != null) {
                if (versionChecker.isMaven3x(candidate)) {
                    return candidate;
                }
                log.warn("MAVEN_HOME points to Maven 4+ ({}), scanning sibling directories", mavenHome);
                String mvn3 = findMaven3InSiblingDirs(Paths.get(mavenHome).getParent());
                if (mvn3 != null) {
                    return mvn3;
                }
            }
        }

        // 5. M2_HOME
        String m2Home = getEnv("M2_HOME");
        if (m2Home != null) {
            String candidate = findMvnInDir(Paths.get(m2Home));
            if (candidate != null) {
                if (versionChecker.isMaven3x(candidate)) {
                    return candidate;
                }
                String mvn3 = findMaven3InSiblingDirs(Paths.get(m2Home).getParent());
                if (mvn3 != null) {
                    return mvn3;
                }
            }
        }

        // 6. MAVEN_HOME sibling rescan (if not already done)
        if (mavenHome != null) {
            Path parent = Paths.get(mavenHome).getParent();
            if (parent != null) {
                String mvn3 = findMaven3InSiblingDirs(parent);
                if (mvn3 != null) {
                    return mvn3;
                }
            }
        }

        // 7. PATH — prefer mvn.cmd over mvn, prefer 3.x
        String pathMvnCmd = findOnPath("mvn.cmd");
        if (pathMvnCmd != null && versionChecker.isMaven3x(pathMvnCmd)) {
            return pathMvnCmd;
        }
        String pathMvn = findOnPath("mvn");
        if (pathMvn != null && versionChecker.isMaven3x(pathMvn)) {
            return pathMvn;
        }

        // 8. Last-resort: any mvn on PATH
        if (pathMvnCmd != null) {
            return pathMvnCmd;
        }
        if (pathMvn != null) {
            return pathMvn;
        }

        // 9. Last-resort: MAVEN_HOME even if 4.x
        if (mavenHome != null) {
            String candidate = findMvnInDir(Paths.get(mavenHome));
            if (candidate != null) {
                log.warn("No Maven 3.x found, falling back to {} (may fail)", candidate);
                return candidate;
            }
        }
        return null;
    }

    private String findMvnInDir(Path homeDir) {
        if (homeDir == null || !Files.isDirectory(homeDir)) {
            return null;
        }
        Path mvn = homeDir.resolve("bin/mvn.cmd");
        if (Files.exists(mvn) && Files.isRegularFile(mvn)) {
            return mvn.toAbsolutePath().toString();
        }
        mvn = homeDir.resolve("bin/mvn");
        if (Files.exists(mvn) && Files.isRegularFile(mvn)) {
            return mvn.toAbsolutePath().toString();
        }
        return null;
    }

    private String findMaven3InSiblingDirs(Path parentDir) {
        if (parentDir == null || !Files.isDirectory(parentDir)) {
            return null;
        }
        try (Stream<Path> dirs = Files.list(parentDir)) {
            return dirs
                    .filter(Files::isDirectory)
                    .map(this::findMvnInDir)
                    .filter(Objects::nonNull)
                    .filter(versionChecker::isMaven3x)
                    .findFirst()
                    .orElse(null);
        } catch (IOException e) {
            log.warn("Failed to scan Maven sibling directories in {}: {}", parentDir, e.getMessage());
            return null;
        }
    }

    private String getEnv(String name) {
        try {
            return System.getenv(name);
        } catch (Exception e) {
            return null;
        }
    }

    private String findOnPath(String name) {
        String pathEnv = getEnv("PATH");
        if (pathEnv == null) {
            return null;
        }
        for (String dir : pathEnv.split(";")) {
            Path candidate = Paths.get(dir.trim(), name);
            if (Files.exists(candidate)) {
                return candidate.toAbsolutePath().toString();
            }
        }
        return null;
    }
}
