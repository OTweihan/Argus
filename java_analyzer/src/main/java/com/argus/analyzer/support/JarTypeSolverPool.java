package com.argus.analyzer.support;

import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 进程级 {@link JarTypeSolver} 有界复用池。
 *
 * <p>此前每次 {@code scan()} 为每个 classpath jar 都 {@code new JarTypeSolver}
 * 且从不关闭——内部持有的 {@code JarFile} 句柄只能等 GC 兜底回收，频繁分析 +
 * 大依赖集时 fd/zip 句柄持续累积（Windows 上尤其紧张），且每个 jar 的中央目录
 * 被重复解析。</p>
 *
 * <p><b>为什么是复用池而不是「扫描结束即关闭」</b>：解析出的 {@code CompilationUnit}
 * 会携带符号解析器引用，后续 pass（调用图构造等）在分析全程内对 jar 符号做
 * <em>惰性</em> 解析——提前关闭会让所有跨 jar 解析静默退化为 unresolved。池化后
 * 句柄只在 LRU 淘汰时释放：容量上限（默认 256，经
 * {@code argus.analysis.jar-pool.max-open-jars} 调整）远大于常规单次分析的 jar 数，
 * 正常情况下整个分析生命周期内条目不会被挤出。</p>
 *
 * <p><b>为什么不做进程级预热</b>：池键为 {@code (规范路径, mtime, size)}，预热需要
 * 提前知道将要分析的 classpath 集合，而它在作业提交后才确定；对「全部历史 jar」
 * 预热会让未参与本次分析的数百个句柄白白占用 fd/内存，与 LRU 容量目标相悖。
 * {@code acquire} 本身就在扫描路径上按需打开，预热不减少首次解析总量，只移动时机，
 * 故刻意不做；重复解析的进一步压缩优先依赖命中率观测（{@link #stats()}）驱动
 * 容量调优。</p>
 *
 * <p>依赖升级（jar 内容变化）自动失效重建，不会复用陈旧索引。线程安全：所有池
 * 操作在实例锁内完成；计数器为 AtomicLong，仅作观测口径。</p>
 */
@Component
final class JarTypeSolverPool {

    private static final Logger log = LoggerFactory.getLogger(JarTypeSolverPool.class);

    /** 默认同时保持打开的 jar 上限，见类注释的容量论证。 */
    private static final int DEFAULT_MAX_OPEN_JARS = 256;

    private record JarKey(String path, long mtimeMs, long sizeBytes) {}

    /** 池命中/打开/淘汰观测快照：为容量调优提供数据依据。 */
    record PoolStats(long acquisitions, long hits, long opens, long evictions) {}

    private final int maxOpenJars;

    private final LinkedHashMap<JarKey, JarTypeSolver> open = new LinkedHashMap<>(16, 0.75f, true) {
        @Override
        protected boolean removeEldestEntry(Map.Entry<JarKey, JarTypeSolver> eldest) {
            boolean evict = size() > maxOpenJars;
            if (evict) {
                closeQuietly(eldest.getKey().path(), eldest.getValue());
                long total = evictions.incrementAndGet();
                if (total == 1) {
                    log.warn("JarTypeSolverPool capacity({}) reached: evicted '{}'. An evicted "
                            + "solver may still be referenced by an in-flight analysis and its lazy "
                            + "resolution will degrade to unresolved; consider raising "
                            + "argus.analysis.jar-pool.max-open-jars if this recurs",
                            maxOpenJars, eldest.getKey().path());
                } else {
                    log.debug("JarTypeSolverPool evicted: {} (total evictions={})",
                            eldest.getKey().path(), total);
                }
            }
            return evict;
        }
    };

    private final AtomicLong acquisitions = new AtomicLong();
    private final AtomicLong hits = new AtomicLong();
    private final AtomicLong opens = new AtomicLong();
    private final AtomicLong evictions = new AtomicLong();

    JarTypeSolverPool() {
        this(DEFAULT_MAX_OPEN_JARS);
    }

    JarTypeSolverPool(int maxOpenJars) {
        if (maxOpenJars < 1) {
            throw new IllegalArgumentException("maxOpenJars must be >= 1: " + maxOpenJars);
        }
        this.maxOpenJars = maxOpenJars;
    }

    @Autowired
    JarTypeSolverPool(@Value("${argus.analysis.jar-pool.max-open-jars:256}") int maxOpenJars) {
        this(maxOpenJars);
    }

    /**
     * 返回该 jar 的共享 {@link JarTypeSolver}，必要时打开并登记。
     *
     * @throws IOException jar 无法读取或不是合法 zip（与直接构造语义一致）
     */
    synchronized JarTypeSolver acquire(Path jar) throws IOException {
        acquisitions.incrementAndGet();
        JarKey key = new JarKey(
                jar.toAbsolutePath().normalize().toString(),
                Files.getLastModifiedTime(jar).toMillis(),
                Files.size(jar));
        JarTypeSolver cached = open.get(key);
        if (cached != null) {
            hits.incrementAndGet();
            return cached;
        }
        opens.incrementAndGet();
        JarTypeSolver created = new JarTypeSolver(jar);
        open.put(key, created);
        return created;
    }

    synchronized int pooledCount() {
        return open.size();
    }

    PoolStats stats() {
        return new PoolStats(acquisitions.get(), hits.get(), opens.get(), evictions.get());
    }

    private static void closeQuietly(String path, JarTypeSolver solver) {
        if (solver instanceof AutoCloseable closeable) {
            try {
                closeable.close();
            } catch (Exception e) {
                log.debug("关闭被淘汰的 JarTypeSolver 失败: {} — {}", path, e.getMessage());
            }
        }
    }
}
