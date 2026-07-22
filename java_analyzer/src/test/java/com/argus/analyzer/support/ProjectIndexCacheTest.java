package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.env.MavenConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.time.Duration;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ProjectIndexCacheTest {

    private ProjectIndexCache cache;

    @BeforeEach
    void setUp() {
        cache = new ProjectIndexCache(Duration.ofMinutes(30));
    }

    @Test
    void shouldReturnNullForMiss(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        assertThat(cache.get(key(tempDir, "all"))).isNull();
    }

    @Test
    void shouldReturnCachedValue(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var key = key(tempDir, "all");
        cache.put(key, response);
        assertThat(cache.get(key)).isSameAs(response);
    }

    @Test
    void shouldInvalidateKey(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var key = key(tempDir, "all");
        cache.put(key, response);
        cache.invalidate(key);
        assertThat(cache.get(key)).isNull();
    }

    @Test
    void shouldClearAll(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var key1 = key(tempDir, "all");
        var key2 = key(tempDir, "endpoints");
        cache.put(key1, response);
        cache.put(key2, response);
        cache.clear();
        assertThat(cache.get(key1)).isNull();
        assertThat(cache.get(key2)).isNull();
    }

    @Test
    void shouldSeparateScopeModulesAndMavenConfig(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        MavenConfig offline = new MavenConfig();
        offline.setOffline(true);
        MavenConfig online = new MavenConfig();

        var all = cache.createKey(tempDir, "all", List.of("b", "a"), offline);
        var endpoints = cache.createKey(tempDir, "endpoints", List.of("a", "b"), offline);
        var differentConfig = cache.createKey(tempDir, "all", List.of("a", "b"), online);

        assertThat(all).isNotEqualTo(endpoints);
        assertThat(all).isNotEqualTo(differentConfig);
        assertThat(all.targetModules()).containsExactly("a", "b");
    }

    @Test
    void shouldInvalidateWhenSourceContentChanges(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        Path source = tempDir.resolve("Example.java");
        Files.writeString(source, "class Example {}");
        var before = key(tempDir, "all");
        Files.writeString(source, "class Example { int value; }");
        var after = key(tempDir, "all");

        assertThat(after.sourceFingerprint()).isNotEqualTo(before.sourceFingerprint());
    }

    @ParameterizedTest
    @ValueSource(strings = {"pom.xml", "build.gradle", "build.gradle.kts",
            "settings.gradle", "settings.gradle.kts"})
    void shouldInvalidateWhenBuildFileChanges(String filename,
                                              @org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        Path buildFile = tempDir.resolve(filename);
        Files.writeString(buildFile, "version = '1'");
        var before = key(tempDir, "all");
        Files.writeString(buildFile, "version = '2'");

        assertThat(key(tempDir, "all").sourceFingerprint())
                .isNotEqualTo(before.sourceFingerprint());
    }

    @Test
    void shouldInvalidateWhenMavenSettingsChanges(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        Path settings = tempDir.resolve("settings.xml");
        Files.writeString(settings, "<settings/>");
        MavenConfig config = new MavenConfig();
        config.setSettingsXml(settings.toString());
        var before = cache.createKey(tempDir, "all", List.of(), config);
        Files.writeString(settings, "<settings><offline>true</offline></settings>");

        assertThat(cache.createKey(tempDir, "all", List.of(), config).mavenSignature())
                .isNotEqualTo(before.mavenSignature());
    }

    @Test
    void shouldExpireEntryAfterTtl(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        cache = new ProjectIndexCache(Duration.ofMillis(10), 2);
        AnalyzeResponse response = new AnalyzeResponse(
                List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var key = key(tempDir, "all");
        cache.put(key, response);

        Thread.sleep(20);

        assertThat(cache.get(key)).isNull();
    }

    @Test
    void shouldComputeSameKeyOnlyOnce(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        var key = key(tempDir, "all");
        var response = new AnalyzeResponse(List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        AtomicInteger calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        Runnable lookup = () -> cache.getOrCompute(key, () -> {
            calls.incrementAndGet();
            entered.countDown();
            try {
                release.await();
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(error);
            }
            return response;
        });

        Thread first = new Thread(lookup);
        Thread second = new Thread(lookup);
        first.start();
        entered.await();
        second.start();
        release.countDown();
        first.join();
        second.join();

        assertThat(calls).hasValue(1);
    }

    @Test
    void shouldEvictLeastRecentlyUsedEntry(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        cache = new ProjectIndexCache(Duration.ofMinutes(30), 2);
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        Path firstDir = Files.createDirectory(tempDir.resolve("first"));
        Path secondDir = Files.createDirectory(tempDir.resolve("second"));
        Path thirdDir = Files.createDirectory(tempDir.resolve("third"));
        var first = key(firstDir, "all");
        var second = key(secondDir, "all");
        var third = key(thirdDir, "all");
        cache.put(first, response);
        cache.put(second, response);
        assertThat(cache.get(first)).isSameAs(response);
        cache.put(third, response);

        assertThat(cache.get(first)).isSameAs(response);
        assertThat(cache.get(second)).isNull();
    }

    private ProjectIndexCache.CacheKey key(Path sourcePath, String scope) {
        return cache.createKey(sourcePath, scope, List.of(), new MavenConfig());
    }
}
