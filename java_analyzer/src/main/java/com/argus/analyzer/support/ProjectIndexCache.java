package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.env.MavenConfig;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Supplier;

/**
 * 分析结果索引缓存（LRU + TTL + single-flight）。
 *
 * <p>O-07：缓存键在客户端提供稳定 revision（commit SHA / 内容 SHA-256）时，
 * 使用 revision + Maven 配置指纹 + analyzer/pass 版本，跨快照目录可命中，
 * 且查找不再全量读取源码树。旧客户端未传 revision 时保留现有
 * {@code path + 全量源码指纹} 回退。</p>
 */
@Component
public class ProjectIndexCache {

    private static final Logger log = LoggerFactory.getLogger(ProjectIndexCache.class);
    private static final Duration DEFAULT_TTL = Duration.ofMinutes(30);

    private static final int DEFAULT_MAX_ENTRIES = 128;

    /**
     * 分析 pass 版本（O-07 缓存键组成部分）。当新增/变更会影响缓存结果语义的
     * pass（finding 规则、call graph 构造、endpoint 提取等）时，必须手动递增
     * 该值，使旧版本缓存键失效，避免误用过期结果。
     */
    static final String ANALYZER_PASS_VERSION = "1";

    private final LinkedHashMap<CacheKey, CacheEntry> cache = new LinkedHashMap<>(16, 0.75f, true);
    private final ConcurrentHashMap<CacheKey, CompletableFuture<AnalyzeResponse>> inFlight =
            new ConcurrentHashMap<>();
    private final Duration ttl;
    private final int maxEntries;

    // O-07 指标：缓存命中不再全量读取源码内容，用指纹耗时决定是否继续引入
    // 增量 per-file digest。
    private final AtomicLong cacheLookups = new AtomicLong();
    private final AtomicLong cacheHits = new AtomicLong();
    private final AtomicLong lookupNanos = new AtomicLong();
    private final AtomicLong fingerprintComputations = new AtomicLong();
    private final AtomicLong fingerprintNanos = new AtomicLong();
    private final AtomicLong revisionLookups = new AtomicLong();

    public ProjectIndexCache() {
        this(DEFAULT_TTL, DEFAULT_MAX_ENTRIES);
    }

    public ProjectIndexCache(Duration ttl) {
        this(ttl, DEFAULT_MAX_ENTRIES);
    }

    public ProjectIndexCache(Duration ttl, int maxEntries) {
        this.ttl = ttl;
        this.maxEntries = Math.max(1, maxEntries);
    }

    @Autowired
    public ProjectIndexCache(
            @Value("${argus.analysis.cache.ttl-minutes:30}") long ttlMinutes,
            @Value("${argus.analysis.cache.max-entries:128}") int maxEntries) {
        this(Duration.ofMinutes(Math.max(1, ttlMinutes)), maxEntries);
    }

    public synchronized AnalyzeResponse get(CacheKey key) {
        long start = System.nanoTime();
        try {
            cacheLookups.incrementAndGet();
            CacheEntry entry = cache.get(key);
            if (entry == null) return null;
            if (Instant.now().isAfter(entry.expiresAt())) {
                cache.remove(key);
                log.debug("Cache entry expired for key: {}", key);
                return null;
            }
            cacheHits.incrementAndGet();
            log.debug("Cache hit for key: {}", key);
            return entry.response();
        } finally {
            // 仅统计缓存查找耗时（miss/过期同样计入），不含分析计算耗时。
            lookupNanos.addAndGet(System.nanoTime() - start);
        }
    }

    public synchronized void put(CacheKey key, AnalyzeResponse response) {
        purgeExpired();
        cache.put(key, new CacheEntry(response, Instant.now().plus(ttl)));
        while (cache.size() > maxEntries) {
            CacheKey eldest = cache.keySet().iterator().next();
            cache.remove(eldest);
        }
        log.debug("Cached analysis result for key: {}", key);
    }

    public synchronized void invalidate(CacheKey key) {
        cache.remove(key);
        log.debug("Invalidated cache for key: {}", key);
    }

    public synchronized void clear() {
        cache.clear();
        log.debug("Cache cleared");
    }

    public CacheResult getOrCompute(CacheKey key, Supplier<AnalyzeResponse> supplier) {
        // 查找耗时由 get() 单独统计（不含 supplier 分析耗时）。
        AnalyzeResponse cached = get(key);
        if (cached != null) {
            return new CacheResult(cached, true);
        }

        CompletableFuture<AnalyzeResponse> candidate = new CompletableFuture<>();
        CompletableFuture<AnalyzeResponse> existing = inFlight.putIfAbsent(key, candidate);
        if (existing != null) {
            // single-flight：并发请求等待同一 in-flight 计算结果，也算命中
            AnalyzeResponse joined = existing.join();
            cacheHits.incrementAndGet();
            return new CacheResult(joined, true);
        }
        try {
            AnalyzeResponse response = supplier.get();
            put(key, response);
            candidate.complete(response);
            return new CacheResult(response, false);
        } catch (RuntimeException | Error error) {
            candidate.completeExceptionally(error);
            throw error;
        } finally {
            inFlight.remove(key, candidate);
        }
    }

    /**
     * 兼容旧签名：revision 为空，回退到 path + 全量源码指纹。
     */
    public CacheKey createKey(Path sourcePath, String scope, List<String> targetModules,
                              MavenConfig config) {
        return createKey(sourcePath, scope, targetModules, config, null, null);
    }

    /**
     * 构造缓存键（O-07）。
     *
     * <p>客户端提供 {@code sourceRevision}（或 {@code snapshotDigest}）时，
     * 以 revision 作为内容身份，跨快照目录可命中，且无需全量读取源码树；
     * 两者皆空时回退到 {@code path + sourceFingerprint}。</p>
     */
    public CacheKey createKey(Path sourcePath, String scope, List<String> targetModules,
                              MavenConfig config, String sourceRevision, String snapshotDigest) {
        Path canonical = sourcePath.toAbsolutePath().normalize();
        List<String> modules = targetModules == null ? List.of() : targetModules.stream()
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .distinct()
                .sorted()
                .toList();
        String revision = firstNonBlank(sourceRevision, snapshotDigest);
        boolean revisionBased = revision != null;
        String fingerprint = "";
        String pathComponent = canonical.toString();
        if (revisionBased) {
            // revision 是内容身份：路径仅用于定位文件，不参与缓存键身份，
            // 使同一 commit/内容哈希在不同快照目录间可命中。
            revisionLookups.incrementAndGet();
            pathComponent = "";
        } else {
            fingerprint = timedSourceFingerprint(canonical);
        }
        return new CacheKey(
                pathComponent,
                scope == null ? "all" : scope,
                modules,
                mavenSignature(config),
                fingerprint,
                revision,
                snapshotDigest,
                ANALYZER_PASS_VERSION
        );
    }

    /**
     * 缓存指标（O-07），供运维/监控汇总。见 {@link #metrics()}。
     */
    public Map<String, Object> metrics() {
        long lookups = cacheLookups.get();
        return Map.ofEntries(
                Map.entry("lookup_count", lookups),
                Map.entry("hit_count", cacheHits.get()),
                Map.entry("lookup_ms_total", ms(lookupNanos)),
                Map.entry("avg_lookup_ms", lookups > 0 ? (lookupNanos.get() / 1_000_000.0) / lookups : 0.0),
                Map.entry("fingerprint_computations", fingerprintComputations.get()),
                Map.entry("fingerprint_ms_total", ms(fingerprintNanos)),
                Map.entry("revision_lookups", revisionLookups.get())
        );
    }

    private static double ms(AtomicLong nanos) {
        return Math.round(nanos.get() / 1_000_000.0 * 1000.0) / 1000.0;
    }

    private String timedSourceFingerprint(Path sourcePath) {
        long start = System.nanoTime();
        String fp = sourceFingerprint(sourcePath);
        fingerprintNanos.addAndGet(System.nanoTime() - start);
        fingerprintComputations.incrementAndGet();
        return fp;
    }

    private synchronized void purgeExpired() {
        Instant now = Instant.now();
        cache.entrySet().removeIf(entry -> now.isAfter(entry.getValue().expiresAt()));
    }

    private String sourceFingerprint(Path sourcePath) {
        MessageDigest digest = newDigest();
        List<Path> relevant = new ArrayList<>();
        try (var paths = Files.walk(sourcePath)) {
            paths.filter(Files::isRegularFile)
                    .filter(this::isFingerprintInput)
                    .forEach(relevant::add);
            relevant.sort(Comparator.comparing(path -> sourcePath.relativize(path).toString()));
            byte[] buffer = new byte[8192];
            for (Path path : relevant) {
                String relative = sourcePath.relativize(path).toString().replace('\\', '/');
                digest.update(relative.getBytes(StandardCharsets.UTF_8));
                digest.update((byte) 0);
                try (InputStream input = Files.newInputStream(path)) {
                    int read;
                    while ((read = input.read(buffer)) >= 0) {
                        digest.update(buffer, 0, read);
                    }
                }
                digest.update((byte) 0);
            }
        } catch (Exception error) {
            throw new IllegalStateException("Failed to fingerprint source tree: " + sourcePath, error);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private boolean isFingerprintInput(Path path) {
        String name = path.getFileName().toString();
        return name.endsWith(".java")
                || name.equals("pom.xml")
                || name.equals("build.gradle")
                || name.equals("build.gradle.kts")
                || name.equals("settings.gradle")
                || name.equals("settings.gradle.kts");
    }

    private String mavenSignature(MavenConfig config) {
        MavenConfig resolved = config != null ? config : new MavenConfig();
        return String.join("\u001f",
                Boolean.toString(resolved.isAutoDetect()),
                Boolean.toString(resolved.isGenerateClasspath()),
                Objects.toString(resolved.getClasspathFile(), ""),
                Objects.toString(resolved.getExecutable(), ""),
                Objects.toString(resolved.getSettingsXml(), ""),
                fileFingerprint(resolved.getSettingsXml()),
                Objects.toString(resolved.getLocalRepository(), ""),
                Boolean.toString(resolved.isOffline()),
                Objects.toString(resolved.getDependencyPluginVersion(), ""),
                Long.toString(resolved.getOfflineTimeoutSeconds()),
                Long.toString(resolved.getOnlineTimeoutSeconds()),
                Objects.toString(resolved.getClasspathMode(), ""),
                Boolean.toString(resolved.isPrepareReactorArtifacts())
        );
    }

    private String fileFingerprint(String rawPath) {
        if (rawPath == null || rawPath.isBlank()) return "";
        Path path = Path.of(rawPath).toAbsolutePath().normalize();
        if (!Files.isRegularFile(path)) return "missing";
        MessageDigest digest = newDigest();
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) >= 0) digest.update(buffer, 0, read);
            return HexFormat.of().formatHex(digest.digest());
        } catch (Exception error) {
            throw new IllegalStateException("Failed to fingerprint Maven settings: " + path, error);
        }
    }

    private MessageDigest newDigest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }

    private static String firstNonBlank(String first, String second) {
        if (first != null && !first.isBlank()) return first;
        if (second != null && !second.isBlank()) return second;
        return null;
    }

    public record CacheKey(String sourcePath, String scope, List<String> targetModules,
                           String mavenSignature, String sourceFingerprint,
                           String sourceRevision, String snapshotDigest, String analyzerVersion) {}

    public record CacheResult(AnalyzeResponse response, boolean cacheHit) {}

    private record CacheEntry(AnalyzeResponse response, Instant expiresAt) {}
}
