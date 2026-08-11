package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.api.dto.AnalyzerDiagnostics;
import com.argus.analyzer.api.dto.CallEdge;
import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.Confidence;
import com.argus.analyzer.api.dto.ParseFailureDetail;
import com.argus.analyzer.api.dto.ResolutionType;
import com.argus.analyzer.env.MavenConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.time.Duration;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

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
        assertThat(cache.put(key, response)).isTrue();
        AnalyzeResponse cached = cache.get(key);
        assertThat(cached).isNotNull();
        assertThat(cached).isEqualTo(response);
        // O-08：缓存持有防御性不可变副本，而非调用方原始实例。
        assertThat(cached).isNotSameAs(response);
    }

    @Test
    void shouldInvalidateKey(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var key = key(tempDir, "all");
        cache.put(key, response);
        cache.invalidate(key);
        assertThat(cache.get(key)).isNull();
        // 权重同步回收。
        assertThat(cache.metrics().get("current_weight")).isEqualTo(0L);
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
        assertThat(cache.metrics().get("current_weight")).isEqualTo(0L);
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
        // TTL 过期条目同步回收权重。
        assertThat(cache.metrics().get("current_weight")).isEqualTo(0L);
        assertThat(cache.metrics().get("evictions_by_expiry")).isEqualTo(1L);
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
    void shouldPropagateSupplierExceptionAndCleanInFlight(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        var key = key(tempDir, "all");
        AtomicInteger calls = new AtomicInteger();
        assertThatThrownBy(() -> cache.getOrCompute(key, () -> {
            calls.incrementAndGet();
            throw new IllegalStateException("boom");
        })).isInstanceOf(IllegalStateException.class);

        // in-flight 已清理：再次调用可重新计算，不残留失败 Future。
        AnalyzeResponse response = new AnalyzeResponse(
                List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var second = cache.getOrCompute(key, () -> {
            calls.incrementAndGet();
            return response;
        });
        assertThat(calls).hasValue(2);
        assertThat(second.cacheHit()).isFalse();
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
        assertThat(cache.get(first)).isNotNull();
        cache.put(third, response);

        assertThat(cache.get(first)).isNotNull();
        assertThat(cache.get(second)).isNull();
        assertThat(cache.metrics().get("evictions_by_count")).isEqualTo(1L);
    }

    // ── O-08：权重预算与超大旁路 ──────────────────────────────────────────

    @Test
    void shouldDefendAgainstCallerMutationAfterCache(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        graph.put("com.Example#run()", new CallGraphNode("Example", "run", "()V", List.of()));
        AnalyzeResponse response = new AnalyzeResponse(List.of(), graph, List.of(), List.of(), List.of(), null);
        var key = key(tempDir, "all");
        cache.put(key, response);

        // 调用方继续修改自己的 map，缓存内数据不受影响。
        graph.put("com.Hacked#pwn()", new CallGraphNode("Hacked", "pwn", "()V", List.of()));
        graph.clear();

        AnalyzeResponse cached = cache.get(key);
        assertThat(cached.callGraph()).containsOnlyKeys("com.Example#run()");
        assertThat(cached.callGraph()).isNotSameAs(graph);
    }

    @Test
    void shouldDefendAgainstCallerMutationOfDiagnosticsAfterCache(
            @org.junit.jupiter.api.io.TempDir Path tempDir) {
        // AnalyzerDiagnostics 是可变类：缓存必须防御拷贝，使调用方后续修改不影响缓存内数据。
        AnalyzerDiagnostics diag = new AnalyzerDiagnostics();
        List<ParseFailureDetail> failures = new ArrayList<>();
        diag.setFailedFiles(failures);
        diag.setClasspathWarnings(new ArrayList<>(List.of("warn-1")));
        AnalyzeResponse response = new AnalyzeResponse(
                List.of(), Map.of(), List.of(), List.of(), List.of(), diag);
        var key = key(tempDir, "all");
        cache.put(key, response);

        // 调用方继续修改自己的诊断集合，缓存内数据不受影响。
        failures.add(new ParseFailureDetail("A.java", List.of("boom")));
        diag.getClasspathWarnings().add("warn-2");

        AnalyzerDiagnostics cached = cache.get(key).diagnostics();
        assertThat(cached).isNotSameAs(diag);
        assertThat(cached.getFailedFiles()).isEmpty();
        assertThat(cached.getClasspathWarnings()).containsExactly("warn-1");
    }

    @Test
    void shouldEvictByWeightBeforeEntryLimit(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        AnalyzeResponse response = responseWith(4, 3);
        long perEntryWeight = ResponseWeightEstimator.estimateWeight(response);
        // 条目上限足够宽松，但总权重预算只放得下 2 个条目。
        cache = new ProjectIndexCache(Duration.ofMinutes(30), 100,
                perEntryWeight * 2, Long.MAX_VALUE / 4);
        Path firstDir = Files.createDirectory(tempDir.resolve("first"));
        Path secondDir = Files.createDirectory(tempDir.resolve("second"));
        Path thirdDir = Files.createDirectory(tempDir.resolve("third"));
        var first = key(firstDir, "all");
        var second = key(secondDir, "all");
        var third = key(thirdDir, "all");
        cache.put(first, response);
        cache.put(second, response);
        assertThat(cache.get(first)).isNotNull();
        assertThat(cache.get(second)).isNotNull();
        cache.put(third, response);

        // 第 3 个触发权重淘汰：最久未用的 first 被挤出。
        assertThat(cache.get(first)).isNull();
        assertThat(cache.get(second)).isNotNull();
        assertThat(cache.get(third)).isNotNull();
        assertThat(cache.metrics().get("current_weight"))
                .isEqualTo(perEntryWeight * 2);
        assertThat(cache.metrics().get("evictions_by_weight")).isEqualTo(1L);
    }

    @Test
    void shouldBypassOversizedSingleEntry(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        cache = new ProjectIndexCache(Duration.ofMinutes(30), 100,
                1_000_000L, /* maxSingleEntryWeight */ 1_000L);
        AnalyzeResponse response = responseWith(100, 10);
        long weight = ResponseWeightEstimator.estimateWeight(response);
        assertThat(weight).isGreaterThan(1_000L);

        var key = key(tempDir, "all");
        assertThat(cache.put(key, response)).isFalse();

        assertThat(cache.get(key)).isNull();
        assertThat(cache.metrics().get("current_weight")).isEqualTo(0L);
        assertThat(cache.metrics().get("oversized_bypass_count")).isEqualTo(1L);
    }

    @Test
    void shouldReturnOversizedResultThroughGetOrCompute(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        cache = new ProjectIndexCache(Duration.ofMinutes(30), 100,
                1_000_000L, /* maxSingleEntryWeight */ 1_000L);
        AnalyzeResponse response = responseWith(100, 10);
        var key = key(tempDir, "all");

        var first = cache.getOrCompute(key, () -> response);
        // 旁路不缓存：结果仍返回给调用方。
        assertThat(first.cacheHit()).isFalse();
        assertThat(first.response()).isSameAs(response);

        // 未入缓存：第二次请求会再次执行 supplier。
        var second = cache.getOrCompute(key, () -> response);
        assertThat(second.cacheHit()).isFalse();
    }

    @Test
    void shouldRecordWeightMetrics(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        AnalyzeResponse response = responseWith(3, 2);
        long weight = ResponseWeightEstimator.estimateWeight(response);
        var key = key(tempDir, "all");
        cache.put(key, response);

        Map<String, Object> metrics = cache.metrics();
        assertThat(metrics.get("current_entries")).isEqualTo(1);
        assertThat(metrics.get("current_weight")).isEqualTo(weight);
        assertThat(metrics.get("max_entries")).isEqualTo(128L);
        assertThat(metrics.get("max_total_weight")).isEqualTo(64L * 1024 * 1024);
        assertThat(metrics.get("max_single_entry_weight")).isEqualTo(16L * 1024 * 1024);
        assertThat(metrics.get("evictions_by_weight")).isEqualTo(0L);
        assertThat(metrics.get("evictions_by_count")).isEqualTo(0L);
        assertThat(metrics.get("evictions_by_expiry")).isEqualTo(0L);
        assertThat(metrics.get("oversized_bypass_count")).isEqualTo(0L);
        assertThat(metrics.get("in_flight")).isEqualTo(0L);
    }

    // ── O-07：revision 缓存键 ──────────────────────────────────────────────

    @Test
    void shouldKeyByRevisionAcrossDifferentSnapshotDirs(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws Exception {
        // 同一 commit/content 在不同快照目录间应命中同一缓存键（路径不参与身份）。
        Path dirA = Files.createDirectory(tempDir.resolve("snapshot-A"));
        Path dirB = Files.createDirectory(tempDir.resolve("snapshot-B"));
        Files.writeString(dirA.resolve("Example.java"), "class Example {}");
        Files.writeString(dirB.resolve("Example.java"), "class Example {}");

        var keyA = cache.createKey(dirA, "all", List.of(), new MavenConfig(), "abc123", null);
        var keyB = cache.createKey(dirB, "all", List.of(), new MavenConfig(), "abc123", null);

        assertThat(keyA).isEqualTo(keyB);
        assertThat(keyA.sourcePath()).isEmpty();
        assertThat(keyA.sourceRevision()).isEqualTo("abc123");
    }

    @Test
    void shouldInvalidateWhenRevisionChanges(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        var keyV1 = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "rev-1", null);
        var keyV2 = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "rev-2", null);

        assertThat(keyV2).isNotEqualTo(keyV1);
    }

    @Test
    void shouldPreferSourceRevisionOverSnapshotDigest(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        var key = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "revision", "digest");
        assertThat(key.sourceRevision()).isEqualTo("revision");
        // 缓存键身份由 sourceRevision 决定，snapshotDigest 仅作冗余携带
        var other = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "revision", "other");
        assertThat(other).isEqualTo(key);
    }

    @Test
    void shouldFallbackToSnapshotDigestWhenNoSourceRevision(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        var key = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), null, "digest-only");
        assertThat(key.sourceRevision()).isEqualTo("digest-only");
        assertThat(key.sourcePath()).isEmpty();
    }

    @Test
    void shouldIncludeAnalyzerPassVersionInKey(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        var key = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "rev-1", null);
        assertThat(key.analyzerVersion()).isEqualTo(ProjectIndexCache.ANALYZER_PASS_VERSION);
    }

    @Test
    void shouldRecordCacheMetrics(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        AnalyzeResponse response = new AnalyzeResponse(
                List.of(), Map.of(), List.of(), List.of(), List.of(), null);
        var key = cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "rev-1", null);
        cache.put(key, response);
        assertThat(cache.get(key)).isNotNull();
        assertThat(cache.get(cache.createKey(tempDir, "all", List.of(), new MavenConfig(), "rev-2", null)))
                .isNull();

        Map<String, Object> metrics = cache.metrics();
        assertThat(metrics.get("lookup_count")).isEqualTo(2L);
        assertThat(metrics.get("hit_count")).isEqualTo(1L);
        assertThat(metrics.get("revision_lookups")).isEqualTo(2L);
        assertThat(metrics.get("fingerprint_computations")).isEqualTo(0L);
        // O-08 指标键存在。
        assertThat(metrics).containsKeys(
                "current_entries", "current_weight", "max_total_weight",
                "max_single_entry_weight", "evictions_by_count", "evictions_by_weight",
                "evictions_by_expiry", "oversized_bypass_count", "in_flight");
    }

    private ProjectIndexCache.CacheKey key(Path sourcePath, String scope) {
        return cache.createKey(sourcePath, scope, List.of(), new MavenConfig());
    }

    /** 构造含 nodes 个调用图节点、每个含 edges 条调用边的响应。 */
    private static AnalyzeResponse responseWith(int nodes, int edges) {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        for (int i = 0; i < nodes; i++) {
            List<CallEdge> callees = new ArrayList<>();
            for (int j = 0; j < edges; j++) {
                callees.add(new CallEdge(
                        "com.acme.Thing" + i + "#call" + j,
                        "call" + j,
                        "Thing" + i,
                        ResolutionType.SYMBOL_SOLVER,
                        Confidence.HIGH,
                        List.of("com.acme.Thing" + i),
                        "Thing" + i + ".java",
                        i + j));
            }
            graph.put("com.acme.Thing" + i + "#run()",
                    new CallGraphNode("com.acme.Thing" + i, "run", "()V", callees));
        }
        return new AnalyzeResponse(List.of(), graph, List.of(), List.of(), List.of(), null);
    }
}
