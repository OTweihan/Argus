package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.AnalyzeResponse;
import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.api.dto.EndpointInfo;
import com.argus.analyzer.api.dto.FindingItem;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
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
    void shouldReturnNullForMiss() {
        assertThat(cache.get("nonexistent")).isNull();
    }

    @Test
    void shouldReturnCachedValue() {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of());
        cache.put("test-key", response);
        assertThat(cache.get("test-key")).isSameAs(response);
    }

    @Test
    void shouldInvalidateKey() {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of());
        cache.put("test-key", response);
        cache.invalidate("test-key");
        assertThat(cache.get("test-key")).isNull();
    }

    @Test
    void shouldClearAll() {
        AnalyzeResponse response = new AnalyzeResponse(List.of(), Map.of(), List.of());
        cache.put("key1", response);
        cache.put("key2", response);
        cache.clear();
        assertThat(cache.get("key1")).isNull();
        assertThat(cache.get("key2")).isNull();
    }
}
