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
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CompletableFuture;
import java.util.function.Supplier;

@Component
public class ProjectIndexCache {

    private static final Logger log = LoggerFactory.getLogger(ProjectIndexCache.class);
    private static final Duration DEFAULT_TTL = Duration.ofMinutes(30);

    private static final int DEFAULT_MAX_ENTRIES = 128;

    private final LinkedHashMap<CacheKey, CacheEntry> cache = new LinkedHashMap<>(16, 0.75f, true);
    private final ConcurrentHashMap<CacheKey, CompletableFuture<AnalyzeResponse>> inFlight =
            new ConcurrentHashMap<>();
    private final Duration ttl;
    private final int maxEntries;

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
        CacheEntry entry = cache.get(key);
        if (entry == null) return null;
        if (Instant.now().isAfter(entry.expiresAt())) {
            cache.remove(key);
            log.debug("Cache entry expired for key: {}", key);
            return null;
        }
        log.debug("Cache hit for key: {}", key);
        return entry.response();
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
        AnalyzeResponse cached = get(key);
        if (cached != null) {
            return new CacheResult(cached, true);
        }

        CompletableFuture<AnalyzeResponse> candidate = new CompletableFuture<>();
        CompletableFuture<AnalyzeResponse> existing = inFlight.putIfAbsent(key, candidate);
        if (existing != null) {
            return new CacheResult(existing.join(), true);
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

    public CacheKey createKey(Path sourcePath, String scope, List<String> targetModules,
                              MavenConfig config) {
        Path canonical = sourcePath.toAbsolutePath().normalize();
        List<String> modules = targetModules == null ? List.of() : targetModules.stream()
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .distinct()
                .sorted()
                .toList();
        return new CacheKey(
                canonical.toString(),
                scope == null ? "all" : scope,
                modules,
                mavenSignature(config),
                sourceFingerprint(canonical)
        );
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

    public record CacheKey(String sourcePath, String scope, List<String> targetModules,
                           String mavenSignature, String sourceFingerprint) {}

    public record CacheResult(AnalyzeResponse response, boolean cacheHit) {}

    private record CacheEntry(AnalyzeResponse response, Instant expiresAt) {}
}
