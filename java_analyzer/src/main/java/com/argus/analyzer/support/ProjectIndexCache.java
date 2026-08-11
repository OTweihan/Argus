package com.argus.analyzer.support;

import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.AnalysisScope;
import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
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
import java.util.Collections;
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
 * 分析结果索引缓存（LRU + TTL + single-flight + 按权重限制）。
 *
 * <p>O-07：缓存键在客户端提供稳定 revision（commit SHA / 内容 SHA-256）时，
 * 使用 revision + Maven 配置指纹 + analyzer/pass 版本，跨快照目录可命中，
 * 且查找不再全量读取源码树。旧客户端未传 revision 时保留现有
 * {@code path + 全量源码指纹} 回退。</p>
 *
 * <p>O-08：条目上限之外增加权重预算。每个 {@link AnalysisResult} 由
 * {@link ResponseWeightEstimator} 估算近似堆字节（字符串长度 + 固定开销），
 * 同时约束 {@code maxEntries}、{@code maxTotalWeight} 与
 * {@code maxSingleEntryWeight}：超大响应直接不缓存（oversized bypass），
 * 超出总权重预算按 LRU 淘汰。缓存值在插入时对顶层集合做防御性不可变包装，
 * 避免调用方修改共享响应污染后续请求。</p>
 */
@Component
public class ProjectIndexCache {

    private static final Logger log = LoggerFactory.getLogger(ProjectIndexCache.class);
    private static final Duration DEFAULT_TTL = Duration.ofMinutes(30);

    private static final int DEFAULT_MAX_ENTRIES = 128;

    /** 总权重默认预算（64 MiB，O-08）。以真实大型项目 + 受限 -Xmx 压测后调优。 */
    private static final long DEFAULT_MAX_TOTAL_WEIGHT = 64L * 1024 * 1024;

    /** 单条目权重默认上限（16 MiB，O-08）：超过的响应不缓存。 */
    private static final long DEFAULT_MAX_SINGLE_ENTRY_WEIGHT = 16L * 1024 * 1024;

    /**
     * 分析 pass 版本（O-07 缓存键组成部分）。当新增/变更会影响缓存结果语义的
     * pass（finding 规则、call graph 构造、endpoint 提取等）时，必须手动递增
     * 该值，使旧版本缓存键失效，避免误用过期结果。
     */
    static final String ANALYZER_PASS_VERSION = "1";

    private final LinkedHashMap<CacheKey, CacheEntry> cache = new LinkedHashMap<>(16, 0.75f, true);
    private final ConcurrentHashMap<CacheKey, CompletableFuture<AnalysisResult>> inFlight =
            new ConcurrentHashMap<>();
    private final Duration ttl;
    private final int maxEntries;
    private final long maxTotalWeight;
    private final long maxSingleEntryWeight;

    /** 当前缓存条目的估算总权重（与 {@link #cache} 同锁维护）。 */
    private long totalWeight;

    // O-07 指标：缓存命中不再全量读取源码内容，用指纹耗时决定是否继续引入
    // 增量 per-file digest。
    private final AtomicLong cacheLookups = new AtomicLong();
    private final AtomicLong cacheHits = new AtomicLong();
    private final AtomicLong lookupNanos = new AtomicLong();
    private final AtomicLong fingerprintComputations = new AtomicLong();
    private final AtomicLong fingerprintNanos = new AtomicLong();
    private final AtomicLong revisionLookups = new AtomicLong();

    // O-08 指标：淘汰原因与超大条目旁路。
    private final AtomicLong evictionsByCount = new AtomicLong();
    private final AtomicLong evictionsByWeight = new AtomicLong();
    private final AtomicLong evictionsByExpiry = new AtomicLong();
    private final AtomicLong oversizedBypassCount = new AtomicLong();

    public ProjectIndexCache() {
        this(DEFAULT_TTL, DEFAULT_MAX_ENTRIES, DEFAULT_MAX_TOTAL_WEIGHT, DEFAULT_MAX_SINGLE_ENTRY_WEIGHT);
    }

    public ProjectIndexCache(Duration ttl) {
        this(ttl, DEFAULT_MAX_ENTRIES, DEFAULT_MAX_TOTAL_WEIGHT, DEFAULT_MAX_SINGLE_ENTRY_WEIGHT);
    }

    public ProjectIndexCache(Duration ttl, int maxEntries) {
        this(ttl, maxEntries, DEFAULT_MAX_TOTAL_WEIGHT, DEFAULT_MAX_SINGLE_ENTRY_WEIGHT);
    }

    public ProjectIndexCache(Duration ttl, int maxEntries, long maxTotalWeight, long maxSingleEntryWeight) {
        this.ttl = ttl;
        this.maxEntries = Math.max(1, maxEntries);
        this.maxTotalWeight = Math.max(1, maxTotalWeight);
        this.maxSingleEntryWeight = Math.max(1, maxSingleEntryWeight);
    }

    @Autowired
    public ProjectIndexCache(
            @Value("${argus.analysis.cache.ttl-minutes:30}") long ttlMinutes,
            @Value("${argus.analysis.cache.max-entries:128}") int maxEntries,
            @Value("${argus.analysis.cache.max-total-weight-bytes:67108864}") long maxTotalWeight,
            @Value("${argus.analysis.cache.max-single-entry-weight-bytes:16777216}") long maxSingleEntryWeight) {
        this(Duration.ofMinutes(Math.max(1, ttlMinutes)), maxEntries,
                maxTotalWeight, maxSingleEntryWeight);
    }

    public synchronized AnalysisResult get(CacheKey key) {
        long start = System.nanoTime();
        try {
            cacheLookups.incrementAndGet();
            CacheEntry entry = cache.get(key);
            if (entry == null) return null;
            if (Instant.now().isAfter(entry.expiresAt())) {
                cache.remove(key);
                totalWeight -= entry.weight();
                evictionsByExpiry.incrementAndGet();
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

    /**
     * 插入缓存条目（等价于 {@link #getOrCompute} 的缓存写入路径）。
     *
     * @return 是否真正入缓存；超大条目旁路（不缓存）时返回 {@code false}。
     */
    public synchronized boolean put(CacheKey key, AnalysisResult response) {
        return insert(key, response) != null;
    }

    /**
     * 插入条目：估算权重、防御性不可变包装、超大旁路、LRU + 权重淘汰。
     *
     * <p>必须同步：{@link #getOrCompute} 的 miss 路径绕过 {@link #put} 直接调用，
     * 而 {@code cache} 是普通 {@link LinkedHashMap}。权重估算在锁内完成——只在
     * 一次完整分析结束后执行一次，相对分析耗时可忽略。</p>
     *
     * @return 缓存内持有的响应实例；超大条目旁路（不缓存）时返回 {@code null}。
     */
    private synchronized AnalysisResult insert(CacheKey key, AnalysisResult response) {
        // 先估算再拷贝：将被旁路的超大响应不创建防御副本（原对象直接返回调用方）。
        long weight = ResponseWeightEstimator.estimateWeight(response);
        if (weight > maxSingleEntryWeight || weight > maxTotalWeight) {
            // 超大响应直接不缓存：返回给调用方但不占用预算，避免单个大调用图挤爆堆。
            oversizedBypassCount.incrementAndGet();
            log.warn("Analysis result for key {} estimated at {} bytes exceeds cache budget "
                            + "(single-entry max={}, total max={}); not cached",
                    key, weight, maxSingleEntryWeight, maxTotalWeight);
            return null;
        }
        AnalysisResult safe = immutableView(response);
        purgeExpired();
        CacheEntry previous = cache.put(key, new CacheEntry(safe, Instant.now().plus(ttl), weight));
        if (previous != null) {
            totalWeight -= previous.weight();
        }
        totalWeight += weight;
        evictOverBudget();
        log.debug("Cached analysis result for key: {} (weight={} bytes)", key, weight);
        return safe;
    }

    /** LRU 淘汰：超过条目上限或总权重预算时按最久未使用顺序移除。 */
    private void evictOverBudget() {
        while (cache.size() > maxEntries || totalWeight > maxTotalWeight) {
            if (cache.isEmpty()) {
                // 防御：单条目即超预算时避免死循环。
                break;
            }
            boolean byCount = cache.size() > maxEntries;
            CacheKey eldest = cache.keySet().iterator().next();
            CacheEntry evicted = cache.remove(eldest);
            totalWeight -= evicted.weight();
            if (byCount) {
                evictionsByCount.incrementAndGet();
                log.debug("Evicted cache entry (entry-count limit): {}", eldest);
            } else {
                evictionsByWeight.incrementAndGet();
                log.debug("Evicted cache entry (weight limit): {} (weight={} bytes)",
                        eldest, evicted.weight());
            }
        }
    }

    public synchronized void invalidate(CacheKey key) {
        CacheEntry removed = cache.remove(key);
        if (removed != null) {
            totalWeight -= removed.weight();
        }
        log.debug("Invalidated cache for key: {}", key);
    }

    public synchronized void clear() {
        cache.clear();
        totalWeight = 0;
        log.debug("Cache cleared");
    }

    public CacheResult getOrCompute(CacheKey key, Supplier<AnalysisResult> supplier) {
        // 查找耗时由 get() 单独统计（不含 supplier 分析耗时）。
        AnalysisResult cached = get(key);
        if (cached != null) {
            return new CacheResult(cached, true);
        }

        CompletableFuture<AnalysisResult> candidate = new CompletableFuture<>();
        CompletableFuture<AnalysisResult> existing = inFlight.putIfAbsent(key, candidate);
        if (existing != null) {
            // single-flight：并发请求等待同一 in-flight 计算结果，也算命中
            AnalysisResult joined = existing.join();
            cacheHits.incrementAndGet();
            return new CacheResult(joined, true);
        }
        try {
            AnalysisResult computed = supplier.get();
            AnalysisResult safe = insert(key, computed);
            // 超大条目旁路时 safe 为 null：仍返回计算结果，只是不缓存。
            AnalysisResult result = safe != null ? safe : computed;
            candidate.complete(result);
            return new CacheResult(result, false);
        } catch (RuntimeException | Error error) {
            candidate.completeExceptionally(error);
            throw error;
        } finally {
            inFlight.remove(key, candidate);
        }
    }

    /**
     * 防御性不可变视图：对顶层集合做浅拷贝 + 不可变包装，防止调用方修改共享
     * 响应污染缓存内数据。嵌套集合保持共享（分析完成后视为只读），属"尽量不可变"
     * 的最佳实践——真正的不可变拷贝会付出 O(响应大小) 的额外分配。
     *
     * <p>与顶层集合不同，{@link AnalyzerDiagnostics} 是可变类（全部经 setter 暴露），
     * 必须做防御拷贝：复制全部字段并对内部集合做不可变包装，否则调用方仍能通过
     * {@code diag.getFailedFiles().clear()} 等修改缓存内诊断数据。</p>
     */
    private static AnalysisResult immutableView(AnalysisResult response) {
        if (response == null) return null;
        return new AnalysisResult(
                unmodifiableCopy(response.endpoints()),
                unmodifiableCopy(response.callGraph()),
                unmodifiableCopy(response.findings()),
                unmodifiableCopy(response.executionFlows()),
                unmodifiableCopy(response.clusters()),
                defensiveDiagnostics(response.diagnostics())
        );
    }

    /**
     * 防御拷贝 {@link AnalyzerDiagnostics}：复制全部标量字段，内部 List/Map 用
     * 不可变包装（与 {@link #unmodifiableCopy} 语义一致），使缓存内的诊断数据与
     * 调用方实例完全隔离。
     */
    private static AnalyzerDiagnostics defensiveDiagnostics(AnalyzerDiagnostics diag) {
        if (diag == null) return null;
        AnalyzerDiagnostics copy = new AnalyzerDiagnostics();
        copy.setTotalSourceFiles(diag.getTotalSourceFiles());
        copy.setParsedFileCount(diag.getParsedFileCount());
        copy.setFailedFileCount(diag.getFailedFileCount());
        copy.setFailedFiles(unmodifiableCopy(diag.getFailedFiles()));
        copy.setTotalCalls(diag.getTotalCalls());
        copy.setResolvedHigh(diag.getResolvedHigh());
        copy.setResolvedMedium(diag.getResolvedMedium());
        copy.setResolvedLow(diag.getResolvedLow());
        copy.setUnresolved(diag.getUnresolved());
        copy.setClasspathAvailable(diag.isClasspathAvailable());
        copy.setJarCount(diag.getJarCount());
        copy.setClasspathSource(diag.getClasspathSource());
        copy.setClasspathWarnings(unmodifiableCopy(diag.getClasspathWarnings()));
        copy.setClasspathErrors(unmodifiableCopy(diag.getClasspathErrors()));
        copy.setClasspathCommand(diag.getClasspathCommand());
        copy.setClasspathExitCode(diag.getClasspathExitCode());
        copy.setClasspathDurationMs(diag.getClasspathDurationMs());
        copy.setClasspathStdoutTail(diag.getClasspathStdoutTail());
        copy.setClasspathStderrTail(diag.getClasspathStderrTail());
        copy.setClasspathTimedOut(diag.isClasspathTimedOut());
        copy.setRootPom(diag.getRootPom());
        copy.setModuleCount(diag.getModuleCount());
        copy.setSourceRootCount(diag.getSourceRootCount());
        copy.setModules(unmodifiableCopy(diag.getModules()));
        copy.setClasspathTargetModules(unmodifiableCopy(diag.getClasspathTargetModules()));
        copy.setClasspathFailedModules(unmodifiableCopy(diag.getClasspathFailedModules()));
        copy.setApplicationModuleCount(diag.getApplicationModuleCount());
        copy.setBusinessModuleCount(diag.getBusinessModuleCount());
        copy.setLibraryModuleCount(diag.getLibraryModuleCount());
        copy.setBomModuleCount(diag.getBomModuleCount());
        copy.setModuleTypes(unmodifiableCopy(diag.getModuleTypes()));
        copy.setPassFailures(unmodifiableCopy(diag.getPassFailures()));
        return copy;
    }

    /**
     * 浅拷贝 + 不可变包装。空集合也返回新包装（不共享原引用）：调用方持有的空
     * 可变集合后续 add/clear 不应污染缓存内数据。
     */
    private static <T> List<T> unmodifiableCopy(List<T> list) {
        if (list == null) return null;
        return Collections.unmodifiableList(new ArrayList<>(list));
    }

    private static <K, V> Map<K, V> unmodifiableCopy(Map<K, V> map) {
        if (map == null) return null;
        return Collections.unmodifiableMap(new LinkedHashMap<>(map));
    }

    /**
     * 从 {@link AnalysisCommand} 构造缓存键（O-11）。
     *
     * <p>核心流程不再持有字符串 scope / 分离的参数，统一由不可变命令驱动。</p>
     */
    public CacheKey createKey(AnalysisCommand command, MavenConfig config) {
        return createKey(command.sourcePath(), command.scope(), command.targetModules(), config,
                command.sourceRevision(), command.snapshotDigest());
    }

    /**
     * 兼容便捷签名：revision 为空，回退到 path + 全量源码指纹。
     */
    public CacheKey createKey(Path sourcePath, AnalysisScope scope, List<String> targetModules,
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
    public CacheKey createKey(Path sourcePath, AnalysisScope scope, List<String> targetModules,
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
        // 冗余携带规范化：revision 为内容身份时 snapshotDigest 不参与键身份，
        // 统一置空避免同 revision 不同 digest 的请求产生不同键（O-07 语义）。
        String storedDigest = revisionBased ? null : snapshotDigest;
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
                scope == null ? "all" : scope.wireValue(),
                modules,
                mavenSignature(config),
                fingerprint,
                revision,
                storedDigest,
                ANALYZER_PASS_VERSION
        );
    }

    /**
     * 缓存指标（O-07/O-08），供运维/监控汇总。见 {@link #metrics()}。
     */
    public synchronized Map<String, Object> metrics() {
        long lookups = cacheLookups.get();
        return Map.ofEntries(
                Map.entry("lookup_count", lookups),
                Map.entry("hit_count", cacheHits.get()),
                Map.entry("lookup_ms_total", ms(lookupNanos)),
                Map.entry("avg_lookup_ms", lookups > 0 ? (lookupNanos.get() / 1_000_000.0) / lookups : 0.0),
                Map.entry("fingerprint_computations", fingerprintComputations.get()),
                Map.entry("fingerprint_ms_total", ms(fingerprintNanos)),
                Map.entry("revision_lookups", revisionLookups.get()),
                // O-08：权重预算、淘汰原因与旁路统计。
                Map.entry("current_entries", cache.size()),
                Map.entry("current_weight", totalWeight),
                Map.entry("max_entries", (long) maxEntries),
                Map.entry("max_total_weight", maxTotalWeight),
                Map.entry("max_single_entry_weight", maxSingleEntryWeight),
                Map.entry("evictions_by_count", evictionsByCount.get()),
                Map.entry("evictions_by_weight", evictionsByWeight.get()),
                Map.entry("evictions_by_expiry", evictionsByExpiry.get()),
                Map.entry("oversized_bypass_count", oversizedBypassCount.get()),
                Map.entry("in_flight", (long) inFlight.size())
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
        var iterator = cache.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<CacheKey, CacheEntry> entry = iterator.next();
            if (now.isAfter(entry.getValue().expiresAt())) {
                totalWeight -= entry.getValue().weight();
                evictionsByExpiry.incrementAndGet();
                iterator.remove();
            }
        }
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

    public record CacheResult(AnalysisResult response, boolean cacheHit) {}

    private record CacheEntry(AnalysisResult response, Instant expiresAt, long weight) {}
}
