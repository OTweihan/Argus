package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class ProjectIndexCache {

    private static final Logger log = LoggerFactory.getLogger(ProjectIndexCache.class);
    private static final Duration DEFAULT_TTL = Duration.ofMinutes(30);

    private final Map<String, CacheEntry> cache = new ConcurrentHashMap<>();
    private final Duration ttl;

    public ProjectIndexCache() {
        this(DEFAULT_TTL);
    }

    public ProjectIndexCache(Duration ttl) {
        this.ttl = ttl;
    }

    public AnalyzeResponse get(String key) {
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

    public void put(String key, AnalyzeResponse response) {
        cache.put(key, new CacheEntry(response, Instant.now().plus(ttl)));
        log.debug("Cached analysis result for key: {}", key);
    }

    public void invalidate(String key) {
        cache.remove(key);
        log.debug("Invalidated cache for key: {}", key);
    }

    public void clear() {
        cache.clear();
        log.debug("Cache cleared");
    }

    private record CacheEntry(AnalyzeResponse response, Instant expiresAt) {}
}
