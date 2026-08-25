package com.argus.analyzer.support;

import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

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
 * 句柄只在 LRU 淘汰时释放：容量上限（32）远大于常规单次分析的 jar 数，正常情况
 * 下整个分析生命周期内条目不会被挤出。</p>
 *
 * <p>键为 {@code (规范路径, mtime, size)}：依赖升级（jar 内容变化）自动失效重建，
 * 不会复用陈旧索引。线程安全：所有池操作在实例锁内完成。</p>
 */
final class JarTypeSolverPool {

    private static final Logger log = LoggerFactory.getLogger(JarTypeSolverPool.class);

    /**
     * 同时保持打开的 jar 上限。必须显著大于现实项目的单次依赖集（Spring Boot
     * 单体轻松超过 100 个 jar）：被淘汰的条目可能仍被某个进行中分析的
     * {@code CombinedTypeSolver} 引用，其后的惰性符号解析会静默退化为
     * unresolved——容量取值需让「单次分析 × 并发数」在常规规模下不触发淘汰。
     */
    private static final int MAX_OPEN_JARS = 256;

    private record JarKey(String path, long mtimeMs, long sizeBytes) {}

    private final LinkedHashMap<JarKey, JarTypeSolver> open = new LinkedHashMap<>(16, 0.75f, true) {
        @Override
        protected boolean removeEldestEntry(Map.Entry<JarKey, JarTypeSolver> eldest) {
            boolean evict = size() > MAX_OPEN_JARS;
            if (evict) {
                closeQuietly(eldest.getKey().path(), eldest.getValue());
            }
            return evict;
        }
    };

    /**
     * 返回该 jar 的共享 {@link JarTypeSolver}，必要时打开并登记。
     *
     * @throws IOException jar 无法读取或不是合法 zip（与直接构造语义一致）
     */
    synchronized JarTypeSolver acquire(Path jar) throws IOException {
        JarKey key = new JarKey(
                jar.toAbsolutePath().normalize().toString(),
                Files.getLastModifiedTime(jar).toMillis(),
                Files.size(jar));
        JarTypeSolver cached = open.get(key);
        if (cached != null) {
            return cached;
        }
        JarTypeSolver created = new JarTypeSolver(jar);
        open.put(key, created);
        return created;
    }

    synchronized int pooledCount() {
        return open.size();
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
