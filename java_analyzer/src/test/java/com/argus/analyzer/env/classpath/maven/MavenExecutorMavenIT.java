package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenExecutionException;
import com.argus.analyzer.env.MavenTimeoutException;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Integration tests that require a real Maven installation.
 * Skipped in CI environments — run with {@code -Dgroups=maven-required}.
 *
 * <p>These tests verify that the correct typed exception is thrown
 * for each real Maven failure mode.  Edge cases that cannot be
 * triggered with a real Maven (e.g. "process exited 0 but classpath
 * file was not created") are covered by the mock-based
 * {@link MavenExecutorTest}.
 */
@Tag("integration")
@Tag("maven-required")
@DisplayName("MavenExecutor integration tests (real Maven)")
class MavenExecutorMavenIT {

    private MavenExecutor executor;
    private MavenConfig config;

    @BeforeEach
    void setUp() {
        executor = new MavenExecutor();
        config = new MavenConfig();
        config.setOffline(true);
    }

    @Test
    @DisplayName("Should throw MavenTimeoutException when execution exceeds the timeout")
    void shouldThrowTimeoutException(@TempDir Path tempDir) throws Exception {
        Files.writeString(tempDir.resolve("pom.xml"), """
                <project>
                    <modelVersion>4.0.0</modelVersion>
                    <groupId>test</groupId>
                    <artifactId>test</artifactId>
                    <version>1.0</version>
                </project>
                """);

        assertThatThrownBy(() -> executor.generateClasspath(tempDir, "mvn", config, 1,
                AnalysisProgressListener.NOOP))
                .isInstanceOf(MavenTimeoutException.class)
                .satisfies(e -> {
                    MavenTimeoutException te = (MavenTimeoutException) e;
                    assertThat(te.timedOut()).isTrue();
                    assertThat(te.durationMs()).isGreaterThanOrEqualTo(0);
                });
    }

    @Test
    @DisplayName("Should throw MavenExecutionException when Maven exits with non-zero code")
    void shouldThrowExecutionExceptionForBadGoal(@TempDir Path tempDir) throws Exception {
        Files.writeString(tempDir.resolve("pom.xml"), """
                <project>
                    <modelVersion>4.0.0</modelVersion>
                    <groupId>test</groupId>
                    <artifactId>test</artifactId>
                    <version>1.0</version>
                </project>
                """);

        assertThatThrownBy(() ->
                executor.generateClasspathForModule(tempDir, tempDir.resolve("out.txt"),
                        "mvn", config, 30, "nonexistent:module:1.0",
                        AnalysisProgressListener.NOOP))
                .isInstanceOf(MavenExecutionException.class)
                .satisfies(e -> {
                    MavenExecutionException ee = (MavenExecutionException) e;
                    assertThat(ee.exitCode()).isNotEqualTo(0);
                    assertThat(ee.commandLine()).isNotNull();
                });
    }
}
