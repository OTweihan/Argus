package com.argus.analyzer.support;

import com.argus.analyzer.domain.model.ParseFailureDetail;
import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.JobCancelledException;
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
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Component
public class SourceFileScanner {

    private static final Logger log = LoggerFactory.getLogger(SourceFileScanner.class);

    /** 解析并行度上限（核数再多也不再增加，避免小项目线程开销）。 */
    private static final int MAX_PARSE_THREADS = 8;

    private final JavaParser defaultParser;
    private final SourceScannerCache cache;
    private final JarTypeSolverPool jarPool;
    private final int configuredParseThreads;

    @Autowired
    public SourceFileScanner(JavaParser defaultParser,
                             SourceScannerCache cache,
                             JarTypeSolverPool jarPool,
                             @Value("${argus.analysis.scan.parse-threads:0}") int configuredParseThreads) {
        this.defaultParser = defaultParser;
        this.cache = cache;
        this.jarPool = jarPool;
        this.configuredParseThreads = configuredParseThreads;
    }

    /** 测试/手工装配便捷入口：使用默认容量的进程级 jar 池与自动并行度。 */
    public SourceFileScanner(JavaParser defaultParser, SourceScannerCache cache) {
        this(defaultParser, cache, new JarTypeSolverPool(), 0);
    }

    public SourceFileScanner(JavaParser defaultParser,
                             SourceScannerCache cache,
                             JarTypeSolverPool jarPool) {
        this(defaultParser, cache, jarPool, 0);
    }

    /**
     * 使用默认配置（JAVA_21）扫描源码目录。
     */
    public ScanResult scan(Path sourcePath) {
        return scan(sourcePath, null, List.of());
    }

    /**
     * 扫描源码目录，自动检测项目 Java 版本并配置符号解析器。
     */
    public ScanResult scan(Path sourcePath, ParserConfiguration.LanguageLevel languageLevel) {
        return scan(sourcePath, languageLevel, List.of());
    }

    /**
     * 扫描源码目录，支持 classpath JAR。
     *
     * @param sourcePath      源码根目录
     * @param languageLevel   可选的语言级别，为 null 时自动检测
     * @param classpathJars   外部依赖 JAR 路径列表
     * @return ScanResult 包含解析成功/失败的文件列表
     */
    public ScanResult scan(Path sourcePath, ParserConfiguration.LanguageLevel languageLevel, List<Path> classpathJars) {
        return scan(sourcePath, languageLevel, classpathJars, AnalysisProgressListener.NOOP);
    }

    /**
     * 一次分析内共享的扫描入口（J1）：以 {@link AnalysisContext} 为惰性资源槽，
     * 多个无依赖 pass（endpoints/callgraph/findings）并发调用时只扫描+解析一次，
     * 其余复用同一份 {@link ScanResult}。资源与 context 同生命周期，不进入
     * {@link SourceScannerCache} 的跨请求缓存（后者只缓存语言级别/源码目录/模块
     * 索引，不缓存可变 AST）。
     */
    public ScanResult scanForContext(AnalysisContext context) {
        return context.computeIfAbsent(
                "source-index",
                () -> scan(context.sourcePath(), null, context.classpathJars(), context.progress()));
    }

    /**
     * 扫描源码目录，支持 classpath JAR 与协作取消（O-04）。
     *
     * <p>排除规则：构建输出目录与测试源码（{@code src/test/**}）不参与分析，
     * 口径统一收口于 {@link BuildOutputFilter#isExcludedFromAnalysis}，并与
     * {@link SourceFingerprint} 的缓存键输入保持一致。</p>
     *
     * <p>解析阶段按 CPU 分片并行（各分片独立解析互不依赖）；符号求解在
     * wave-1 各 pass 中本就并发执行同一批 AST，风险类别不变。取消检查保持
     * 在文件边界，失败收集与输出顺序确定（按相对路径排序）。</p>
     *
     * @param sourcePath      源码根目录
     * @param languageLevel   可选的语言级别，为 null 时自动检测
     * @param classpathJars   外部依赖 JAR 路径列表
     * @param progress        进度/取消通道；取消时在文件循环安全边界抛
     *                        {@link JobCancelledException}
     * @return ScanResult 包含解析成功/失败的文件列表
     */
    public ScanResult scan(Path sourcePath, ParserConfiguration.LanguageLevel languageLevel,
                           List<Path> classpathJars, AnalysisProgressListener progress) {
        ParserConfiguration.LanguageLevel level = languageLevel != null
                ? languageLevel
                : cache.getLanguageLevel(sourcePath);

        CombinedTypeSolver typeSolver = buildTypeSolver(sourcePath, classpathJars);

        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(level);
        config.setSymbolResolver(new JavaSymbolSolver(typeSolver));

        List<Path> javaFiles;
        try (var files = Files.walk(sourcePath)) {
            javaFiles = files
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> !isExcludedFromAnalysis(p))
                    .toList();
        } catch (IOException e) {
            log.error("Failed to walk source path: {}", sourcePath, e);
            return new ScanResult(List.of(), List.of(), 0);
        }

        ChunkResult result = parseFiles(sourcePath, javaFiles, config, progress);
        // 输出按相对路径排序：并行分片合并后仍与串行路径保持确定性一致。
        result.parsedFiles().sort(Comparator.comparing(entry -> entry.getKey().toString()));
        result.failures().sort(Comparator.comparing(ParseFailureDetail::file));

        return new ScanResult(result.parsedFiles(), result.failures(), javaFiles.size());
    }

    /** 单个解析分片的结果（分片间无共享可变状态）。 */
    private record ChunkResult(
            List<Map.Entry<Path, CompilationUnit>> parsedFiles,
            List<ParseFailureDetail> failures) {}

    /**
     * 解析全部文件：文件数少或并行度为 1 时走串行；否则按目标线程数分片，
     * 每个分片独立持有 {@link JavaParser}（非线程安全），共享同一份
     * {@link ParserConfiguration}（构建后只读）。
     */
    private ChunkResult parseFiles(Path sourcePath,
                                   List<Path> javaFiles,
                                   ParserConfiguration config,
                                   AnalysisProgressListener progress) {
        int threads = resolveParseThreads(javaFiles.size());
        if (threads <= 1 || javaFiles.size() < 2) {
            return parseChunk(sourcePath, javaFiles, config, progress);
        }

        List<List<Path>> chunks = partition(javaFiles, threads);
        AtomicInteger seq = new AtomicInteger();
        ThreadFactory factory = task -> {
            Thread thread = new Thread(task, "argus-scan-parse-" + seq.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        };
        // Java 21：ExecutorService 实现 AutoCloseable，close() 等待在跑任务收尾；
        // 取消路径上各分片在文件边界协作退出，不会拖住 close()。
        try (ExecutorService executor = Executors.newFixedThreadPool(chunks.size(), factory)) {
            List<Future<ChunkResult>> futures = new ArrayList<>(chunks.size());
            for (List<Path> chunk : chunks) {
                futures.add(executor.submit(() -> parseChunk(sourcePath, chunk, config, progress)));
            }
            List<Map.Entry<Path, CompilationUnit>> parsedFiles = new ArrayList<>();
            List<ParseFailureDetail> failures = new ArrayList<>();
            for (Future<ChunkResult> future : futures) {
                try {
                    ChunkResult part = future.get();
                    parsedFiles.addAll(part.parsedFiles());
                    failures.addAll(part.failures());
                } catch (ExecutionException e) {
                    if (e.getCause() instanceof JobCancelledException cancelled) {
                        throw cancelled;
                    }
                    throw new IllegalStateException("Source scan chunk failed", e.getCause());
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new JobCancelledException("Source scan interrupted");
                }
            }
            return new ChunkResult(parsedFiles, failures);
        }
    }

    private ChunkResult parseChunk(Path sourcePath,
                                   List<Path> files,
                                   ParserConfiguration config,
                                   AnalysisProgressListener progress) {
        JavaParser parser = new JavaParser(config);
        List<Map.Entry<Path, CompilationUnit>> parsedFiles = new ArrayList<>();
        List<ParseFailureDetail> failures = new ArrayList<>();

        for (Path javaFile : files) {
            if (progress.isCancelled()) {
                throw new JobCancelledException("Source scan cancelled");
            }
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
        return new ChunkResult(parsedFiles, failures);
    }

    /** 把文件列表近似均分为 {@code parts} 个连续分片。 */
    private static List<List<Path>> partition(List<Path> files, int parts) {
        List<List<Path>> chunks = new ArrayList<>(parts);
        int chunkSize = (files.size() + parts - 1) / parts;
        for (int i = 0; i < files.size(); i += chunkSize) {
            chunks.add(files.subList(i, Math.min(i + chunkSize, files.size())));
        }
        return chunks;
    }

    /**
     * 解析并行度：显式配置 &gt; 0 时取配置值；否则取
     * {@code min(MAX_PARSE_THREADS, availableProcessors)}。
     */
    private int resolveParseThreads(int fileCount) {
        int threads;
        if (configuredParseThreads > 0) {
            threads = configuredParseThreads;
        } else {
            threads = Math.min(MAX_PARSE_THREADS, Runtime.getRuntime().availableProcessors());
        }
        return Math.max(1, Math.min(threads, fileCount));
    }

    private CombinedTypeSolver buildTypeSolver(Path sourcePath, List<Path> classpathJars) {
        CombinedTypeSolver typeSolver = new CombinedTypeSolver();
        typeSolver.add(new ReflectionTypeSolver());
        if (sourcePath != null && Files.isDirectory(sourcePath)) {
            for (Path srcDir : cache.getSourceDirectories(sourcePath)) {
                typeSolver.add(new JavaParserTypeSolver(srcDir));
            }
        }
        for (Path jar : classpathJars) {
            if (Files.exists(jar)) {
                try {
                    // 复用池化 solver：消除每次扫描的 fd 累积与 zip 重复解析；
                    // AST 后续惰性解析依赖 solver 存活，故不能按次关闭（见池类注释）。
                    typeSolver.add(jarPool.acquire(jar));
                } catch (Exception e) {
                    log.warn("Failed to load JarTypeSolver for: {} — {}", jar, e.getMessage());
                }
            } else {
                log.warn("Classpath JAR not found, skipping: {}", jar);
            }
        }
        return typeSolver;
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

    /**
     * 获取当前项目对应的 Maven 模块索引。
     *
     * @param sourcePath 源码根目录
     * @return 模块索引，如非 Maven 项目或扫描失败则返回 null
     */
    public MavenModuleIndex getCurrentModuleIndex(Path sourcePath) {
        return cache.getModuleIndex(sourcePath);
    }

    public static String relativize(Path sourcePath, Path filePath) {
        return sourcePath.relativize(filePath).toString();
    }

    /**
     * 判断路径是否被排除出分析输入（构建输出 + 测试源码）。
     *
     * <p>规则统一收口于 {@link BuildOutputFilter}（与源码指纹共用同一口径）；
     * 目录名按路径段精确匹配，避免子串匹配把 {@code TargetService.java}、
     * {@code targeting/} 等合法源码一并排除。</p>
     */
    private static boolean isExcludedFromAnalysis(Path path) {
        return BuildOutputFilter.isExcludedFromAnalysis(path);
    }
}
