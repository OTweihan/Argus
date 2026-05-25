package com.argus.analyzer.env;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;

/**
 * Maven 根 POM 定位器。
 *
 * <p>从用户传入的目录出发，按以下优先级定位：
 * <ol>
 *   <li>当前目录有 pom.xml</li>
 *   <li>搜索子目录找到聚合 POM（含 &lt;modules&gt;）</li>
 *   <li>向上搜父目录找 pom.xml</li>
 * </ol>
 */
@Component
public class MavenProjectLocator {

    private static final Logger log = LoggerFactory.getLogger(MavenProjectLocator.class);
    private static final int MAX_DEPTH = 5;

    /**
     * 定位项目根 POM。
     *
     * @param inputPath 用户传入的目录
     * @return 根 POM 路径，找不到返回 empty
     */
    public Optional<Path> locateRootPom(Path inputPath) {
        log.info("[POM_LOCATOR] Starting search from input path: {}", inputPath);

        // 1. 当前目录
        Path currentPom = inputPath.resolve("pom.xml");
        if (Files.exists(currentPom)) {
            log.info("[POM_LOCATOR] Found POM at input path: {} (aggregator={})",
                    currentPom, isAggregatorPom(currentPom));
            return Optional.of(currentPom);
        }
        log.info("[POM_LOCATOR] No pom.xml at input path, searching subdirectories...");

        // 2. 搜索子目录，优先选聚合 POM
        List<Path> aggregatorPoms = new ArrayList<>();
        List<Path> allPoms = new ArrayList<>();
        try {
            Files.walkFileTree(inputPath, Set.of(FileVisitOption.FOLLOW_LINKS), MAX_DEPTH, new SimpleFileVisitor<>() {
                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                    if (file.getFileName().toString().equals("pom.xml")) {
                        allPoms.add(file);
                        if (isAggregatorPom(file)) {
                            aggregatorPoms.add(file);
                        }
                    }
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                    String name = dir.getFileName().toString();
                    if (name.startsWith(".") || "target".equals(name) || "node_modules".equals(name)) {
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    return FileVisitResult.CONTINUE;
                }
            });
        } catch (IOException e) {
            log.warn("Failed to search for POM files in {}: {}", inputPath, e.getMessage());
        }

        log.info("[POM_LOCATOR] Found {} total POMs, {} aggregator POMs", allPoms.size(), aggregatorPoms.size());

        // 优先返回最靠近 inputPath 的聚合 POM
        if (!aggregatorPoms.isEmpty()) {
            aggregatorPoms.sort(Comparator.comparingInt(p -> inputPath.relativize(p).getNameCount()));
            Path chosen = aggregatorPoms.get(0);
            log.info("[POM_LOCATOR] Selected aggregator POM: {} (depth={})",
                    chosen, inputPath.relativize(chosen).getNameCount());
            return Optional.of(chosen);
        }

        // 3. 向上搜父目录
        log.info("[POM_LOCATOR] No aggregator POM found, searching parent directories...");
        Path parent = inputPath.getParent();
        while (parent != null) {
            Path parentPom = parent.resolve("pom.xml");
            if (Files.exists(parentPom)) {
                log.info("[POM_LOCATOR] Found POM in parent directory: {} (aggregator={})",
                        parentPom, isAggregatorPom(parentPom));
                return Optional.of(parentPom);
            }
            log.info("[POM_LOCATOR] No pom.xml in parent: {}", parent);
            parent = parent.getParent();
        }

        log.warn("[POM_LOCATOR] No pom.xml found from input path: {}", inputPath);
        return Optional.empty();
    }

    /**
     * 检查 POM 是否包含 {@code <modules>} 标签（粗略判断）。
     */
    public static boolean isAggregatorPom(Path pomFile) {
        try {
            String content = Files.readString(pomFile);
            // 找 <modules> 但不被 XML 注释包围
            int idx = content.indexOf("<modules>");
            if (idx < 0) return false;
            // 确保不在注释中
            int commentStart = content.lastIndexOf("<!--", idx);
            int commentEnd = content.lastIndexOf("-->", idx);
            return commentStart < 0 || (commentEnd > commentStart);
        } catch (IOException e) {
            return false;
        }
    }
}
