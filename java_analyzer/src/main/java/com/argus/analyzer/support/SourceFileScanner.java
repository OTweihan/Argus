package com.argus.analyzer.support;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ast.CompilationUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 共享的源码文件扫描器。
 *
 * 统一负责 walk 源码目录 → 过滤 .java → 排除 target/ → 解析为 CompilationUnit，
 * 避免 {@code ControllerExtractor}、{@code CallGraphBuilder}、{@code FindingDetector}
 * 各自重复文件遍历逻辑。
 */
@Component
public class SourceFileScanner {

    private static final Logger log = LoggerFactory.getLogger(SourceFileScanner.class);

    private final JavaParser parser;

    public SourceFileScanner(JavaParser parser) {
        this.parser = parser;
    }

    /**
     * 扫描源码目录，返回 (相对路径, CompilationUnit) 列表。
     *
     * @param sourcePath 源码根目录
     * @return 可解析的 Java 文件列表，解析失败的自动跳过并记 warn 日志
     */
    public List<Map.Entry<Path, CompilationUnit>> scan(Path sourcePath) {
        List<Map.Entry<Path, CompilationUnit>> results = new ArrayList<>();

        try (var files = Files.walk(sourcePath)) {
            List<Path> javaFiles = files
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> !p.toString().contains("target"))
                    .toList();

            for (Path javaFile : javaFiles) {
                try {
                    CompilationUnit cu = parser.parse(javaFile)
                            .getResult()
                            .orElseThrow(() -> new IOException("Failed to parse: " + javaFile));
                    results.add(new AbstractMap.SimpleEntry<>(javaFile, cu));
                } catch (IOException e) {
                    log.warn("Failed to parse file: {}", javaFile, e);
                }
            }
        } catch (IOException e) {
            log.error("Failed to walk source path: {}", sourcePath, e);
        }

        return results;
    }

    /**
     * 返回相对于 sourcePath 的路径字符串。
     */
    public static String relativize(Path sourcePath, Path filePath) {
        return sourcePath.relativize(filePath).toString();
    }
}
