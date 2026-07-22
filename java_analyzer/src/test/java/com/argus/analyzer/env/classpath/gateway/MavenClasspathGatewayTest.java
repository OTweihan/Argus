package com.argus.analyzer.env.classpath.gateway;

import com.argus.analyzer.env.ClasspathException;
import com.argus.analyzer.env.ClasspathGenerationException;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenExecutionException;
import com.argus.analyzer.env.MavenNotFoundException;
import com.argus.analyzer.env.MavenTimeoutException;
import com.argus.analyzer.env.classpath.maven.MavenDetector;
import com.argus.analyzer.env.classpath.maven.MavenExecutor;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MavenClasspathGatewayTest {

    @Mock
    private MavenDetector mavenDetector;

    @Mock
    private MavenExecutor mavenExecutor;

    @InjectMocks
    private MavenClasspathGateway gateway;

    @Test
    void shouldConvertTimeoutExceptionToClasspathResult() {
        MavenTimeoutException ex = new MavenTimeoutException(
                "Timed out after 30s",
                30L, "mvn dependency:build-classpath",
                12500L, "[stdout]", "[stderr]");

        when(mavenExecutor.generateClasspath(any(), anyString(), any(), anyLong(), any()))
                .thenThrow(ex);

        ClasspathResult result = gateway.generateClasspath(
                Path.of("/tmp"), "mvn", new MavenConfig(), 60, AnalysisProgressListener.NOOP);

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.isTimedOut()).isTrue();
        assertThat(result.isFallback()).isTrue();
        assertThat(result.getDurationMs()).isEqualTo(12500L);
        assertThat(result.getStdoutTail()).isEqualTo("[stdout]");
        assertThat(result.getStderrTail()).isEqualTo("[stderr]");
        assertThat(result.getCommand()).isEqualTo("mvn dependency:build-classpath");
        assertThat(result.getErrors()).contains("Timed out after 30s");
    }

    @Test
    void shouldConvertExecutionExceptionToClasspathResult() {
        MavenExecutionException ex = new MavenExecutionException(
                "Maven exited with code 1: [ERROR] Compilation failure",
                1, "mvn dependency:build-classpath",
                "[ERROR] Compilation failure", 5000L, "[Building...]");

        when(mavenExecutor.generateClasspath(any(), anyString(), any(), anyLong(), any()))
                .thenThrow(ex);

        ClasspathResult result = gateway.generateClasspath(
                Path.of("/tmp"), "mvn", new MavenConfig(), 60, AnalysisProgressListener.NOOP);

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.getExitCode()).isEqualTo(1);
        assertThat(result.getCommand()).isEqualTo("mvn dependency:build-classpath");
        assertThat(result.getDurationMs()).isEqualTo(5000L);
        assertThat(result.getStderrTail()).isEqualTo("[ERROR] Compilation failure");
        assertThat(result.getStdoutTail()).isEqualTo("[Building...]");
        assertThat(result.isTimedOut()).isFalse();
    }

    @Test
    void shouldConvertGenerationExceptionWithFullContext() {
        ClasspathGenerationException ex = new ClasspathGenerationException(
                "Maven completed but classpath file was not created",
                "mvn dependency:build-classpath", 0, 8000L,
                "[INFO] BUILD SUCCESS", "[WARNING] no sources");

        when(mavenExecutor.generateClasspath(any(), anyString(), any(), anyLong(), any()))
                .thenThrow(ex);

        ClasspathResult result = gateway.generateClasspath(
                Path.of("/tmp"), "mvn", new MavenConfig(), 60, AnalysisProgressListener.NOOP);

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.isFallback()).isTrue();
        assertThat(result.getExitCode()).isEqualTo(0);
        assertThat(result.getDurationMs()).isEqualTo(8000L);
        assertThat(result.getStdoutTail()).isEqualTo("[INFO] BUILD SUCCESS");
        assertThat(result.getStderrTail()).isEqualTo("[WARNING] no sources");
        assertThat(result.getCommand()).isEqualTo("mvn dependency:build-classpath");
    }

    @Test
    void shouldConvertGenerationExceptionWithoutContext() {
        ClasspathGenerationException ex = new ClasspathGenerationException(
                "Maven execution failed: No such file",
                new java.io.IOException("No such file"));

        when(mavenExecutor.generateClasspath(any(), anyString(), any(), anyLong(), any()))
                .thenThrow(ex);

        ClasspathResult result = gateway.generateClasspath(
                Path.of("/tmp"), "mvn", new MavenConfig(), 60, AnalysisProgressListener.NOOP);

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.isFallback()).isTrue();
        assertThat(result.getCommand()).isNull();
        assertThat(result.getExitCode()).isNull();
        assertThat(result.getDurationMs()).isNull();  // -1 → not set
        assertThat(result.getErrors()).contains("Maven execution failed: No such file");
    }

    @Test
    void shouldConvertMavenNotFoundException() {
        MavenNotFoundException ex = new MavenNotFoundException(
                "Maven executable not found", "mvn");

        when(mavenExecutor.generateClasspath(any(), anyString(), any(), anyLong(), any()))
                .thenThrow(ex);

        ClasspathResult result = gateway.generateClasspath(
                Path.of("/tmp"), "mvn", new MavenConfig(), 60, AnalysisProgressListener.NOOP);

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.isFallback()).isTrue();
        assertThat(result.getCommand()).isEqualTo("mvn");
        assertThat(result.getExitCode()).isNull();
    }

    @Test
    void shouldPassThroughSuccessResult() {
        ClasspathResult success = new ClasspathResult(true, true, false,
                List.of("/path/to/a.jar", "/path/to/b.jar"), "maven-online-system",
                List.of(), List.of(), "mvn ...", 0);
        success.setDurationMs(3000L);

        when(mavenExecutor.generateClasspath(any(), anyString(), any(), anyLong(), any()))
                .thenReturn(success);

        ClasspathResult result = gateway.generateClasspath(
                Path.of("/tmp"), "mvn", new MavenConfig(), 60, AnalysisProgressListener.NOOP);

        assertThat(result.isAvailable()).isTrue();
        assertThat(result.isGenerated()).isTrue();
        assertThat(result.getJars()).hasSize(2);
        assertThat(result.getSource()).isEqualTo("maven-online-system");
        assertThat(result.getDurationMs()).isEqualTo(3000L);
        assertThat(result.isTimedOut()).isFalse();
    }
}
