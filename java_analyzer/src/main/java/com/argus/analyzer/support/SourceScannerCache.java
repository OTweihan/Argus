package com.argus.analyzer.support;

import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.MavenModuleScanner;
import com.argus.analyzer.env.MavenProjectLocator;
import com.github.javaparser.ParserConfiguration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * SourceFileScanner 的缓存状态持有者。
 *
 * <p>将 mutable 缓存字段从 Spring 单例服务中分离出来，
 * 使 SourceFileScanner 回归无状态语义，同时保持线程安全。
 */
@Component
public class SourceScannerCache {

    private static final Logger log = LoggerFactory.getLogger(SourceScannerCache.class);

    private final MavenProjectLocator projectLocator;
    private final MavenModuleScanner moduleScanner;

    private String lastSourcePath;
    private ParserConfiguration.LanguageLevel lastLevel;
    private String lastSourceDirsPath;
    private List<Path> lastSourceDirs;
    private MavenModuleIndex currentModuleIndex;
    private String lastModuleIndexPath;

    public SourceScannerCache(MavenProjectLocator projectLocator,
                              MavenModuleScanner moduleScanner) {
        this.projectLocator = projectLocator;
        this.moduleScanner = moduleScanner;
    }

    synchronized ParserConfiguration.LanguageLevel getLanguageLevel(Path sourcePath) {
        String pathStr = sourcePath.toAbsolutePath().normalize().toString();
        if (!pathStr.equals(lastSourcePath)) {
            lastLevel = JavaVersionDetector.detect(sourcePath);
            lastSourcePath = pathStr;
        }
        return lastLevel;
    }

    synchronized List<Path> getSourceDirectories(Path sourcePath) {
        String pathStr = sourcePath.toAbsolutePath().normalize().toString();
        if (!pathStr.equals(lastSourceDirsPath)) {
            log.info("[SOURCE_DIRS] Resolving source directories for: {}", pathStr);

            MavenModuleIndex pomIndex = tryBuildModuleIndex(sourcePath);
            if (pomIndex != null) {
                List<Path> sourceRoots = pomIndex.getAllSourceRoots();
                log.info("[SOURCE_DIRS] POM-based discovery: {} source roots from {} modules",
                        sourceRoots.size(), pomIndex.getNonAggregatorModuleCount());
                if (!sourceRoots.isEmpty()) {
                    currentModuleIndex = pomIndex;
                    lastModuleIndexPath = pathStr;
                    lastSourceDirs = sourceRoots;
                    lastSourceDirsPath = pathStr;
                    return lastSourceDirs;
                }
                log.info("[SOURCE_DIRS] POM found but no source roots, falling back to directory scan");
            } else {
                log.info("[SOURCE_DIRS] No Maven POM found, using directory scan");
            }

            lastSourceDirs = SourceFileScanner.resolveSourceDirectories(sourcePath);
            lastSourceDirsPath = pathStr;
            log.info("[SOURCE_DIRS] Directory scan result: {} source directories", lastSourceDirs.size());
        }
        return lastSourceDirs;
    }

    synchronized MavenModuleIndex getModuleIndex(Path sourcePath) {
        getSourceDirectories(sourcePath); // 确保缓存已初始化
        String pathStr = sourcePath.toAbsolutePath().normalize().toString();
        return pathStr.equals(lastModuleIndexPath) ? currentModuleIndex : null;
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
