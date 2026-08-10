package com.argus.analyzer.support;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.List;

@Component
public class SourceLocator {

    private static final Logger log = LoggerFactory.getLogger(SourceLocator.class);

    private final List<Path> allowedSourceRoots;

    /**
     * 无参构造（宽松模式）：测试专用。注意 Spring 启动总走下方 @Autowired 构造；
     * application.yml 默认把 allowed-source-roots 解析为 `${java.io.tmpdir}/argus_sources`
     * （裸机 fail-closed 默认根目录），不会落到空列表。空列表仅意味着"Java 不限制
     * 根目录"，此时仍执行 real-path 校验，但对外暴露任意可见目录。
     */
    public SourceLocator() {
        this(List.of());
    }

    @Autowired
    public SourceLocator(
            @Value("${argus.analysis.allowed-source-roots:}") String allowedSourceRoots) {
        this(_parseRoots(allowedSourceRoots));
    }

    SourceLocator(List<Path> allowedSourceRoots) {
        this.allowedSourceRoots = allowedSourceRoots;
        if (allowedSourceRoots.isEmpty()) {
            log.warn("argus.analysis.allowed-source-roots 未配置，源码路径校验处于宽松模式"
                    + "（允许 Java 进程可见的任意目录）；生产/容器部署请显式配置。");
        } else {
            log.info("源码路径边界：allowed source roots = {}", allowedSourceRoots);
        }
    }

    /**
     * 解析源码路径（宽松模式）：仅绝对路径归一化、存在性和目录校验。
     * 兼容旧调用方；新代码应使用 {@link #resolveForAnalysis(String)} 以获得
     * real-path 边界校验。
     */
    public Path resolve(String sourcePath) {
        Path path = Paths.get(sourcePath).toAbsolutePath().normalize();

        if (!Files.exists(path)) {
            throw new IllegalArgumentException("Source path does not exist: " + path);
        }
        if (!Files.isDirectory(path)) {
            throw new IllegalArgumentException("Source path is not a directory: " + path);
        }

        log.info("Resolved source path: {}", path);
        return path;
    }

    /**
     * 解析并校验源码路径（fail-closed）。
     *
     * 在 {@link #resolve} 的基础上增加：
     * - 经 {@code toRealPath()} 解析所有中间组件，拒绝符号链接逃逸（指向
     *   allowed roots 之外的链接，其 real 路径不会命中任何根目录）；
     * - 若配置了 allowed source roots，real 路径必须位于其中一个根目录内。
     *
     * analyze 与 validate-source 统一走本方法，保证两侧边界一致。
     */
    public Path resolveForAnalysis(String sourcePath) {
        Path resolved = resolve(sourcePath);
        Path realPath;
        try {
            realPath = resolved.toRealPath();
        } catch (IOException error) {
            throw new IllegalArgumentException(
                    "Failed to resolve real path: " + resolved, error);
        }
        if (!Files.isDirectory(realPath, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("Source path is not a directory: " + realPath);
        }
        if (!allowedSourceRoots.isEmpty() && !isWithinAllowedRoots(realPath)) {
            throw new IllegalArgumentException(
                    "Source path outside allowed roots: " + realPath
                            + " (allowed: " + allowedSourceRoots + ")");
        }
        log.info("Resolved and validated source path: {}", realPath);
        return realPath;
    }

    private boolean isWithinAllowedRoots(Path realPath) {
        for (Path root : allowedSourceRoots) {
            Path realRoot;
            try {
                realRoot = root.toRealPath();
            } catch (IOException error) {
                log.warn("Allowed root unavailable, ignoring: {} ({})", root, error.getMessage());
                continue;
            }
            if (realPath.startsWith(realRoot)) {
                return true;
            }
        }
        return false;
    }

    private static List<Path> _parseRoots(String raw) {
        if (raw == null || raw.isBlank()) {
            return List.of();
        }
        return Arrays.stream(raw.split(","))
                .map(String::trim)
                .filter(part -> !part.isEmpty())
                .map(Path::of)
                .toList();
    }
}
