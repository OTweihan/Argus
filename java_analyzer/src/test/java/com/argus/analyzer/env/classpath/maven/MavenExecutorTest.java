package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.ClasspathGenerationException;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.service.MavenProcessRegistry;
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
import static org.mockito.Mockito.verify;
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
        executor = new MavenExecutor(streamExecutor, new MavenProcessRegistry());
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

    @Test
    @DisplayName("Cooperative cancellation kills process tree and propagates JobCancelledException (O-04)")
    void shouldCancelProcessTreeWhenListenerCancelled(@org.junit.jupiter.api.io.TempDir Path tempDir)
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
        // 进程永不退出——取消只能通过 isCancelled() 判定
        when(mockProcess.waitFor(any(Long.TYPE), any(TimeUnit.class))).thenReturn(false);
        when(mockProcess.isAlive()).thenReturn(true);
        when(mockProcess.pid()).thenReturn(999L);
        when(mockProcess.descendants()).thenReturn(java.util.stream.Stream.empty());
        when(mockProcess.onExit()).thenReturn(new java.util.concurrent.CompletableFuture<>());

        // 第一次调用返回 false（进入轮询），随后置位取消
        AnalysisProgressListener cancelling = new AnalysisProgressListener() {
            private int calls;

            @Override
            public void onEvent(String stage, String level, String message) {
            }

            @Override
            public boolean isCancelled() {
                return calls++ > 0;
            }
        };

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
                            "mvn", config, 60, null, cancelling))
                    .isInstanceOf(JobCancelledException.class);
            // 取消路径必须强制销毁进程（含 descendants 强杀）
            verify(mockProcess).destroyForcibly();
        }
    }

}
