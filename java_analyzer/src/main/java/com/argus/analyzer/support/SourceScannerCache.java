package com.argus.analyzer.support;

import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.MavenModuleScanner;
import com.argus.analyzer.env.MavenProjectLocator;
import com.github.javaparser.ParserConfiguration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * SourceFileScanner 的缓存状态持有者。
 *
 * <p>将 mutable 缓存字段从 Spring 单例服务中分离出来，
 * 使 SourceFileScanner 回归无状态语义，同时保持线程安全。</p>
 *
 * <p>缓存按 sourcePath 键控（带容量上限的 access-order LRU）。此前是单槽缓存：
 * 两个作业线程分析不同项目时每次都会互相覆盖、重复 {@code tryBuildModuleIndex} /
 * {@code getLanguageLevel}，且 {@code getModuleIndex} 隐式依赖先调
 * {@code getSourceDirectories} 才能命中。改为 Map 后，每个项目持有独立条目，
 * 并消除调用顺序耦合。</p>
 */
@Component
public class SourceScannerCache {

    private static final Logger log = LoggerFactory.getLogger(SourceScannerCache.class);

    private static final int MAX_ENTRIES = 16;

    private final MavenProjectLocator projectLocator;
    private final MavenModuleScanner moduleScanner;

    // access-order LinkedHashMap：最近访问的条目排在末尾，容量超限时淘汰最久未用。
    // 所有读写都在 synchronized 方法内，无需额外并发结构。
    private final Map<String, Entry> cache = new LinkedHashMap<>(MAX_ENTRIES, 0.75f, true) {
        @Override
        protected boolean removeEldestEntry(Map.Entry<String, Entry> eldest) {
            return size() > MAX_ENTRIES;
        }
    };

    private record Entry(
            ParserConfiguration.LanguageLevel languageLevel,
            List<Path> sourceDirectories,
            MavenModuleIndex moduleIndex
    ) {}

    public SourceScannerCache(MavenProjectLocator projectLocator,
                              MavenModuleScanner moduleScanner) {
        this.projectLocator = projectLocator;
        this.moduleScanner = moduleScanner;
    }

    synchronized ParserConfiguration.LanguageLevel getLanguageLevel(Path sourcePath) {
        return entry(sourcePath).languageLevel();
    }

    synchronized List<Path> getSourceDirectories(Path sourcePath) {
        return entry(sourcePath).sourceDirectories();
    }

    synchronized MavenModuleIndex getModuleIndex(Path sourcePath) {
        return entry(sourcePath).moduleIndex();
    }

    private Entry entry(Path sourcePath) {
        String pathStr = sourcePath.toAbsolutePath().normalize().toString();
        Entry cached = cache.get(pathStr);
        if (cached != null) {
            return cached;
        }
        Entry built = build(sourcePath);
        cache.put(pathStr, built);
        return built;
    }

    private Entry build(Path sourcePath) {
        ParserConfiguration.LanguageLevel level = JavaVersionDetector.detect(sourcePath);
        MavenModuleIndex pomIndex = tryBuildModuleIndex(sourcePath);
        if (pomIndex != null) {
            List<Path> sourceRoots = pomIndex.getAllSourceRoots();
            log.info("[SOURCE_DIRS] POM-based discovery: {} source roots from {} modules",
                    sourceRoots.size(), pomIndex.getNonAggregatorModuleCount());
            if (!sourceRoots.isEmpty()) {
                return new Entry(level, List.copyOf(sourceRoots), pomIndex);
            }
            log.info("[SOURCE_DIRS] POM found but no source roots, falling back to directory scan");
        } else {
            log.info("[SOURCE_DIRS] No Maven POM found, using directory scan");
        }
        // 非 Maven 项目或 POM 无 source roots：moduleIndex 保持 null（与旧单槽缓存
        // 语义一致——仅「POM 有 source roots」时才记录模块索引供 classpath 解析使用）。
        List<Path> dirs = SourceFileScanner.resolveSourceDirectories(sourcePath);
        log.info("[SOURCE_DIRS] Directory scan result: {} source directories", dirs.size());
        return new Entry(level, List.copyOf(dirs), null);
    }

    private MavenModuleIndex tryBuildModuleIndex(Path sourcePath) {
        try {
            log.info("[POM_INDEX] Attempting to build Maven module index for: {}", sourcePath);
            Optional<Path> rootPom = projectLocator.locateRootPom(sourcePath);
            if (rootPom.isPresent()) {
                log.info("[POM_INDEX] Root POM found: {}, starting module scan...", rootPom.get());
                MavenModuleIndex index = moduleScanner.scan(rootPom.get());
                log.info("[POM_INDEX] Module index built: {} modules, {} source roots",
                        index.getModuleCount(), index.getAllSourceRoots().size());
                return index;
            } else {
                log.info("[POM_INDEX] No root POM found for: {}", sourcePath);
                return null;
            }
        } catch (Exception e) {
            log.warn("[POM_INDEX] Maven module scan failed for {}: {}", sourcePath, e.getMessage(), e);
            return null;
        }
    }
}
