package com.argus.analyzer.service;

import org.junit.jupiter.api.Test;

import java.util.concurrent.CompletableFuture;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * O-04：Maven 进程注册表——取消/超时/terminate 时销毁整个进程树。
 */
class MavenProcessRegistryTest {

    @Test
    void shouldDestroyProcessTreeForRegisteredKey() {
        MavenProcessRegistry registry = new MavenProcessRegistry();
        AnalysisProgressListener key = (stage, level, message) -> {
        };

        Process process = mock(Process.class);
        ProcessHandle child = mock(ProcessHandle.class);
        when(process.isAlive()).thenReturn(true);
        when(process.pid()).thenReturn(123L);
        when(process.descendants()).thenReturn(Stream.of(child));
        when(process.onExit()).thenReturn(new CompletableFuture<>());

        registry.register(key, process);
        registry.destroyFor(key);

        verify(process).destroyForcibly();
        verify(child).destroyForcibly();
    }

    @Test
    void shouldIgnoreNoopKeyForNonJobPaths() {
        MavenProcessRegistry registry = new MavenProcessRegistry();
        Process process = mock(Process.class);

        // NOOP（同步 /analyze 路径）不登记 → 不触发 onExit，destroy 为 no-op
        assertThatCode(() -> registry.register(AnalysisProgressListener.NOOP, process)).doesNotThrowAnyException();
        assertThatCode(() -> registry.destroyFor(AnalysisProgressListener.NOOP)).doesNotThrowAnyException();
        verify(process, never()).destroyForcibly();
    }
}
