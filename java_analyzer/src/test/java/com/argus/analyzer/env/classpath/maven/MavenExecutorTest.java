package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.ClasspathGenerationException;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.MockedConstruction;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockConstruction;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link MavenExecutor} that mock {@link ProcessBuilder}
 * to cover error paths that cannot be triggered with a real Maven installation.
 *
 * <p>The "Maven exits 0 but classpath file is missing" path is covered
 * at the Gateway level by
 * {@link com.argus.analyzer.env.classpath.gateway.MavenClasspathGatewayTest#shouldConvertGenerationExceptionWithFullContext}.
 */
@DisplayName("MavenExecutor unit tests (mocked ProcessBuilder)")
class MavenExecutorTest {

    private MavenExecutor executor;
    private MavenConfig config;
    private ExecutorService streamExecutor;

    @BeforeEach
    void setUp() {
        streamExecutor = Executors.newVirtualThreadPerTaskExecutor();
        executor = new MavenExecutor(streamExecutor);
        config = new MavenConfig();
        config.setOffline(true);
    }

    @AfterEach
    void tearDown() {
        streamExecutor.close();
    }

    @Test
    @DisplayName("Should throw ClasspathGenerationException wrapping IOException when process fails to start")
    void shouldThrowIOExceptionAsGenerationException(@org.junit.jupiter.api.io.TempDir Path tempDir) throws Exception {
        Files.writeString(tempDir.resolve("pom.xml"), """
                <project>
                    <modelVersion>4.0.0</modelVersion>
                    <groupId>test</groupId>
                    <artifactId>test</artifactId>
                    <version>1.0</version>
                </project>
                """);

        Path outputDir = tempDir.resolve(".argus");
        try {
            Files.createDirectories(outputDir);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        Path outputFile = outputDir.resolve("classpath.txt");

        try (MockedConstruction<ProcessBuilder> ignored = mockConstruction(ProcessBuilder.class,
                (mockPb, ctx) -> {
                    when(mockPb.redirectErrorStream(any(Boolean.TYPE))).thenReturn(mockPb);
                    try {
                        when(mockPb.start()).thenThrow(new IOException("Cannot run program"));
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                })) {

            assertThatThrownBy(() ->
                    executor.generateClasspathForModule(tempDir, outputFile,
                            "mvn", config, 60, null,
                            AnalysisProgressListener.NOOP))
                    .isInstanceOf(ClasspathGenerationException.class)
                    .satisfies(e -> {
                        ClasspathGenerationException ge = (ClasspathGenerationException) e;
                        assertThat(ge.getCause()).isInstanceOf(IOException.class);
                        assertThat(ge.getMessage()).contains("Maven execution failed");
                    });
        }
    }

    @Test
    @DisplayName("Should throw ClasspathGenerationException and restore interrupt when process is interrupted")
    void shouldThrowInterruptedExceptionAsGenerationException(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        Files.writeString(tempDir.resolve("pom.xml"), """
                <project>
                    <modelVersion>4.0.0</modelVersion>
                    <groupId>test</groupId>
                    <artifactId>test</artifactId>
                    <version>1.0</version>
                </project>
                """);

        Path outputDir = tempDir.resolve(".argus");
        Files.createDirectories(outputDir);
        Path outputFile = outputDir.resolve("classpath.txt");

        Process mockProcess = mock(Process.class);
        when(mockProcess.getInputStream()).thenReturn(InputStream.nullInputStream());
        when(mockProcess.getErrorStream()).thenReturn(InputStream.nullInputStream());
        when(mockProcess.waitFor(any(Long.TYPE), any(TimeUnit.class)))
                .thenThrow(new InterruptedException("interrupted"));

        try (MockedConstruction<ProcessBuilder> ignored = mockConstruction(ProcessBuilder.class,
                (mockPb, ctx) -> {
                    when(mockPb.redirectErrorStream(any(Boolean.TYPE))).thenReturn(mockPb);
                    try {
                        when(mockPb.start()).thenReturn(mockProcess);
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                })) {

            assertThatThrownBy(() ->
                    executor.generateClasspathForModule(tempDir, outputFile,
                            "mvn", config, 60, null,
                            AnalysisProgressListener.NOOP))
                    .isInstanceOf(ClasspathGenerationException.class)
                    .satisfies(e -> {
                        ClasspathGenerationException ge = (ClasspathGenerationException) e;
                        assertThat(ge.getMessage()).isEqualTo("Maven execution interrupted");
                    });
        }
    }

}
