package com.argus.analyzer.support;

import com.argus.analyzer.api.dto.ParseFailureDetail;
import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.Problem;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
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
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Component
public class SourceFileScanner {

    private static final Logger log = LoggerFactory.getLogger(SourceFileScanner.class);

    private final JavaParser defaultParser;
    private String lastSourcePath;
    private ParserConfiguration.LanguageLevel lastLevel;
    private String lastSourceDirsPath;
    private List<Path> lastSourceDirs;

    public SourceFileScanner(JavaParser defaultParser) {
        this.defaultParser = defaultParser;
    }

    /**
     * 使用默认配置（JAVA_21）扫描源码目录。
     */
    public ScanResult scan(Path sourcePath) {
        return scan(sourcePath, null);
    }

    /**
     * 扫描源码目录，自动检测项目 Java 版本并配置符号解析器。
     *
     * @param sourcePath      源码根目录
     * @param languageLevel   可选的语言级别，为 null 时自动检测
     * @return ScanResult 包含解析成功/失败的文件列表
     */
    public ScanResult scan(Path sourcePath, ParserConfiguration.LanguageLevel languageLevel) {
        List<Map.Entry<Path, CompilationUnit>> parsedFiles = new ArrayList<>();
        List<ParseFailureDetail> failures = new ArrayList<>();

        ParserConfiguration.LanguageLevel level = languageLevel != null
                ? languageLevel
                : detectLanguageLevel(sourcePath);

        CombinedTypeSolver typeSolver = new CombinedTypeSolver();
        typeSolver.add(new ReflectionTypeSolver());
        if (sourcePath != null && Files.isDirectory(sourcePath)) {
            for (Path srcDir : getSourceDirectories(sourcePath)) {
                typeSolver.add(new JavaParserTypeSolver(srcDir));
            }
        }

        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(level);
        config.setSymbolResolver(new JavaSymbolSolver(typeSolver));
        JavaParser parser = new JavaParser(config);

        List<Path> javaFiles;
        try (var files = Files.walk(sourcePath)) {
            javaFiles = files
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> !p.toString().contains("target"))
                    .toList();
        } catch (IOException e) {
            log.error("Failed to walk source path: {}", sourcePath, e);
            return new ScanResult(List.of(), List.of(), 0);
        }

        for (Path javaFile : javaFiles) {
            try {
                var parseResult = parser.parse(javaFile);
                if (parseResult.isSuccessful() && parseResult.getResult().isPresent()) {
                    parsedFiles.add(new AbstractMap.SimpleEntry<>(javaFile, parseResult.getResult().get()));
                } else {
                    List<String> problems = parseResult.getProblems().stream()
                            .map(Problem::toString)
                            .collect(Collectors.toList());
                    String relativePath = relativize(sourcePath, javaFile);
                    failures.add(new ParseFailureDetail(relativePath, problems));
                    log.warn("Failed to parse: {} — problems: {}", relativePath, problems);
                }
            } catch (Exception e) {
                String relativePath = relativize(sourcePath, javaFile);
                failures.add(new ParseFailureDetail(relativePath, List.of(e.getMessage())));
                log.warn("Failed to parse: {} — {}", relativePath, e.getMessage());
            }
        }

        return new ScanResult(parsedFiles, failures, javaFiles.size());
    }

    /**
     * ScanResult 包装类，包含解析成功/失败的文件列表及统计信息。
     */
    public record ScanResult(
            List<Map.Entry<Path, CompilationUnit>> parsedFiles,
            List<ParseFailureDetail> failures,
            int totalFiles
    ) {}

    /**
     * 解析项目源码目录列表。支持：
     * - 单模块项目：直接返回 sourcePath
     * - 多模块 Maven 项目：扫描各模块下的 src/main/java
     */
    static List<Path> resolveSourceDirectories(Path sourcePath) {
        List<Path> dirs = new ArrayList<>();
        Path mainSrc = sourcePath.resolve("src/main/java");
        if (Files.isDirectory(mainSrc)) {
            dirs.add(mainSrc);
            return dirs;
        }

        try (Stream<Path> entries = Files.list(sourcePath)) {
            entries.filter(Files::isDirectory)
                    .map(module -> module.resolve("src/main/java"))
                    .filter(Files::isDirectory)
                    .forEach(dirs::add);
        } catch (IOException e) {
            log.warn("Failed to scan for module source directories: {}", e.getMessage());
        }

        if (dirs.isEmpty()) {
            dirs.add(sourcePath);
        } else {
            log.info("Discovered {} Maven module source directories", dirs.size());
        }
        return dirs;
    }

    private synchronized List<Path> getSourceDirectories(Path sourcePath) {
        String pathStr = sourcePath.toAbsolutePath().normalize().toString();
        if (!pathStr.equals(lastSourceDirsPath)) {
            lastSourceDirs = resolveSourceDirectories(sourcePath);
            lastSourceDirsPath = pathStr;
        }
        return lastSourceDirs;
    }

    private synchronized ParserConfiguration.LanguageLevel detectLanguageLevel(Path sourcePath) {
        String pathStr = sourcePath.toAbsolutePath().normalize().toString();
        if (!pathStr.equals(lastSourcePath)) {
            lastLevel = JavaVersionDetector.detect(sourcePath);
            lastSourcePath = pathStr;
        }
        return lastLevel;
    }

    public static String relativize(Path sourcePath, Path filePath) {
        return sourcePath.relativize(filePath).toString();
    }
}
