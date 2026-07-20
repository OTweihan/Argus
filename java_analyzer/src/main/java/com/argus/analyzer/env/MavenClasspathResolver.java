package com.argus.analyzer.env;

import com.argus.analyzer.service.AnalysisProgressListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

@Service
public class MavenClasspathResolver {

    private static final Logger log = LoggerFactory.getLogger(MavenClasspathResolver.class);
    private static final String CACHE_FILE = ".argus/classpath.txt";
    private static final String CACHE_DIR = ".argus/classpath";
    private static final int MAVEN_OUTPUT_TAIL_CHARS = 4000;

    /**
     * 按优先级链解析 classpath。
     *
     * <ol>
     *   <li>用户显式指定的 classpath 文件</li>
     *   <li>缓存文件 {@code .argus/classpath.txt} — 有效 JAR 存在时直接返回</li>
     *   <li>离线 Maven 生成（{@code -o}，短超时）</li>
     *   <li>联网 Maven 生成（长超时）</li>
     *   <li>陈旧缓存 — 即使 JAR 缺失也尝试使用</li>
     *   <li>降级为无 classpath</li>
     * </ol>
     */
    public ClasspathResult resolve(Path sourcePath, MavenConfig config) {
        return resolve(sourcePath, config, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult resolve(Path sourcePath, MavenConfig config, AnalysisProgressListener progress) {
        // 1. 用户显式传入 classpath 文件
        if (config.getClasspathFile() != null && !config.getClasspathFile().isEmpty()) {
            Path cpFile = sourcePath.resolve(config.getClasspathFile());
            if (Files.exists(cpFile)) {
                ClasspathResult result = readClasspathFile(cpFile, "explicit");
                log.info("[CLASSPATH] Step 0: explicit file — loaded {} jars from {}", result.getJars().size(), cpFile);
                return result;
            }
            log.warn("[CLASSPATH] Step 0: explicit file not found: {}", cpFile);
        }

        // 2. 缓存文件：读取并检查是否有可用 JAR
        Path cachedFile = sourcePath.resolve(CACHE_FILE);
        boolean cacheFileExists = Files.exists(cachedFile);
        log.info("[CLASSPATH] Step A: checking cache at {} ... exists={}", cachedFile, cacheFileExists);
        ClasspathResult cacheResult = cacheFileExists ? readClasspathFile(cachedFile, "cache") : null;

        if (cacheResult != null && cacheResult.hasValidJars()) {
            log.info("[CLASSPATH] Step A: cache hit — {} valid jars, using directly", cacheResult.getJars().size());
            return cacheResult;
        }
        log.info("[CLASSPATH] Step A: cache skipped ({}), proceeding to Maven generation",
                cacheResult != null ? "hasValidJars=false" : "file not found");

        // 3/4. 自动 Maven 生成：先离线（短超时），后联网（长超时）
        if (config.isAutoDetect() && config.isGenerateClasspath()) {
            String mvnExec = detectMavenExecutable(sourcePath, config);
            if (mvnExec != null) {
                // 3. 离线模式（短超时）
                long offlineTimeout = config.getOfflineTimeoutSeconds();
                log.info("[CLASSPATH] Step B: starting offline Maven generation (timeout={}s) ...", offlineTimeout);
                MavenConfig offlineConfig = config.withOffline(true);
                ClasspathResult offlineResult = generateClasspath(sourcePath, mvnExec, offlineConfig, offlineTimeout, progress);
                if (offlineResult.isAvailable()) {
                    log.info("[CLASSPATH] Step B: offline Maven succeeded — {} jars", offlineResult.getJars().size());
                    return offlineResult;
                }
                log.warn("[CLASSPATH] Step B: offline Maven failed — {}", offlineResult.getErrors());

                // 4. 联网模式（长超时）
                long onlineTimeout = config.getOnlineTimeoutSeconds();
                log.info("[CLASSPATH] Step C: starting online Maven generation (timeout={}s) ...", onlineTimeout);
                MavenConfig onlineConfig = config.withOffline(false);
                ClasspathResult onlineResult = generateClasspath(sourcePath, mvnExec, onlineConfig, onlineTimeout, progress);
                if (onlineResult.isAvailable()) {
                    log.info("[CLASSPATH] Step C: online Maven succeeded — {} jars", onlineResult.getJars().size());
                    return onlineResult;
                }
                log.warn("[CLASSPATH] Step C: online Maven failed — {}", onlineResult.getErrors());
            } else {
                log.warn("[CLASSPATH] No Maven executable found, skipping steps B/C");
            }
        } else {
            log.info("[CLASSPATH] Steps B/C: skipped (autoDetect={}, generateClasspath={})",
                    config.isAutoDetect(), config.isGenerateClasspath());
        }

        // 5. 陈旧缓存：文件存在但 JAR 可能缺失
        if (cacheResult != null) {
            log.info("[CLASSPATH] Step D: using stale cache — {} jars (may be incomplete)", cacheResult.getJars().size());
            cacheResult.setFallback(true);
            cacheResult.setSource("cache-stale");
            warningsFor(cacheResult).add("Using stale cache — some or all JARs may be missing");
            return cacheResult;
        }
        log.info("[CLASSPATH] Step D: no stale cache available");

        // 6. 全部失败，降级
        log.warn("[CLASSPATH] Step E: all steps failed, falling back to source-only analysis");
        return ClasspathResult.unavailable("No classpath available; fallback to source-only analysis");
    }

    // ====== P1: 模块感知的 classpath 解析 ======

    public ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules, MavenConfig config) {
        return resolve(moduleIndex, targetModules, config, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules, MavenConfig config,
                                   AnalysisProgressListener progress) {
        if (targetModules == null || targetModules.isEmpty()) {
            log.info("[CLASSPATH] No target modules specified, using legacy resolve");
            return resolve(moduleIndex.getBasedir(), config, progress);
        }

        log.info("[CLASSPATH] Module-aware resolve: {} target modules: {}", targetModules.size(), targetModules);
        List<String> allJars = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        List<String> succeeded = new ArrayList<>();
        List<String> failed = new ArrayList<>();
        ClasspathResult firstExecutionDiagnostics = null;

        for (String targetModule : targetModules) {
            log.info("[CLASSPATH] Resolving classpath for module: {}", targetModule);
            ClasspathResult moduleResult = resolveForModule(moduleIndex, targetModule, config, progress);
            if (moduleResult.isAvailable() && moduleResult.hasValidJars()) {
                allJars.addAll(moduleResult.getJars());
                succeeded.add(targetModule);
                if (firstExecutionDiagnostics == null && moduleResult.getCommand() != null) {
                    firstExecutionDiagnostics = moduleResult;
                }
                log.info("[CLASSPATH] Module {}: {} jars", targetModule, moduleResult.getJars().size());
            } else {
                failed.add(targetModule);
                warnings.addAll(moduleResult.getWarnings());
                errors.addAll(moduleResult.getErrors());
                if (firstExecutionDiagnostics == null && moduleResult.getCommand() != null) {
                    firstExecutionDiagnostics = moduleResult;
                }
                log.warn("[CLASSPATH] Module {}: failed — {}", targetModule, moduleResult.getErrors());
            }
        }

        if (allJars.isEmpty()) {
            log.warn("[CLASSPATH] All target modules failed, falling back");
            ClasspathResult unavailable = ClasspathResult.unavailable("All target modules failed: " + String.join(", ", failed));
            unavailable.setWarnings(warnings);
            unavailable.setErrors(errors);
            unavailable.copyExecutionDiagnosticsFrom(firstExecutionDiagnostics);
            return unavailable;
        }

        ClasspathResult merged = new ClasspathResult();
        merged.setAvailable(true);
        merged.setJars(allJars);
        merged.setSource("module-aware");
        merged.setGenerated(true);
        merged.setWarnings(warnings);
        merged.setErrors(errors);
        if (firstExecutionDiagnostics != null) {
            merged.copyExecutionDiagnosticsFrom(firstExecutionDiagnostics);
        }
        log.info("[CLASSPATH] Module-aware classpath: {} total jars from {} modules (succeeded={}, failed={})",
                allJars.size(), targetModules.size(), succeeded.size(), failed.size());
        return merged;
    }

    private ClasspathResult resolveForModule(MavenModuleIndex moduleIndex, String moduleSelector, MavenConfig config,
                                             AnalysisProgressListener progress) {
        var optModule = moduleIndex.findModule(moduleSelector);
        if (optModule.isEmpty()) {
            return ClasspathResult.unavailable("Module not found in index: " + moduleSelector);
        }

        MavenModule module = optModule.get();
        String moduleKey = module.getDisplayName();
        Path projectRoot = moduleIndex.getBasedir();
        Path cacheDir = projectRoot.resolve(CACHE_DIR);
        Path cacheFile = cacheDir.resolve(toCacheFileName(moduleKey));
        Path metaFile = cacheDir.resolve(toMetaFileName(moduleKey));

        // ClasspathMode 分发
        ClasspathMode mode = config.getClasspathMode();
        log.info("[CLASSPATH] Module {}: classpathMode={}", moduleKey, mode);

        if (mode == ClasspathMode.SOURCE_ONLY) {
            log.info("[CLASSPATH] Module {}: SOURCE_ONLY mode, skipping classpath", moduleKey);
            return ClasspathResult.unavailable("classpathMode=SOURCE_ONLY");
        }

        // Step A: per-module cache（带元数据校验）
        log.info("[CLASSPATH] Module {}: checking cache at {}", moduleKey, cacheFile);
        if (Files.exists(cacheFile)) {
            ClasspathResult cached = readClasspathFile(cacheFile, "cache-" + moduleKey);
            if (cached.hasValidJars()) {
                if (isCacheValid(metaFile, moduleIndex, config)) {
                    log.info("[CLASSPATH] Module {}: cache hit valid ({} jars)", moduleKey, cached.getJars().size());
                    return cached;
                }
                log.info("[CLASSPATH] Module {}: cache stale (pom/settings changed), regenerating", moduleKey);
            }
        }

        if (mode == ClasspathMode.CACHE_ONLY) {
            log.info("[CLASSPATH] Module {}: CACHE_ONLY mode, no valid cache", moduleKey);
            return ClasspathResult.unavailable("No valid cache for module: " + moduleKey + " (mode=CACHE_ONLY)");
        }

        // Detect Maven
        String mvnExec = detectMavenExecutable(projectRoot, config);
        if (mvnExec == null) {
            log.warn("[CLASSPATH] Module {}: no Maven executable found", moduleKey);
            return fallbackToSourceOnly(moduleKey);
        }

        // Ensure cache dir
        try {
            Files.createDirectories(cacheDir);
        } catch (IOException e) {
            log.warn("[CLASSPATH] Module {}: failed to create cache dir: {}", moduleKey, e.getMessage());
            return fallbackToSourceOnly(moduleKey);
        }

        // prepareReactorArtifacts：先安装 reactor 内部模块
        if (config.isPrepareReactorArtifacts()) {
            log.info("[CLASSPATH] Module {}: preparing reactor artifacts (mvn install -DskipTests)", moduleKey);
            boolean prepared = runMvnInstall(projectRoot, mvnExec, config.getOnlineTimeoutSeconds(), progress);
            if (!prepared) {
                log.warn("[CLASSPATH] Module {}: reactor artifact preparation failed, continuing anyway", moduleKey);
            }
        }

        String projectSelector = toMavenProjectSelector(moduleSelector, module);

        // AUTO 模式：online → offline
        // MAVEN 模式：按 config.offline 决定
        boolean tryOnlineFirst = !config.isOffline();
        boolean tryOffline = true;

        if (tryOnlineFirst) {
            // Step B: online（长超时）
            long onTimeout = config.getOnlineTimeoutSeconds();
            log.info("[CLASSPATH] Module {}: online generation (timeout={}s)", moduleKey, onTimeout);
            ClasspathResult onlineResult = generateClasspathForModule(projectRoot, cacheFile, mvnExec,
                    config.withOffline(false), onTimeout, projectSelector, progress);
            if (onlineResult.isAvailable() && onlineResult.hasValidJars()) {
                saveCacheMetadata(metaFile, moduleIndex, config);
                log.info("[CLASSPATH] Module {}: online succeeded ({} jars)", moduleKey, onlineResult.getJars().size());
                return onlineResult;
            }
            log.warn("[CLASSPATH] Module {}: online failed", moduleKey);
        }

        // Step C: offline（短超时）
        if (tryOffline) {
            long offTimeout = config.getOfflineTimeoutSeconds();
            log.info("[CLASSPATH] Module {}: offline generation (timeout={}s)", moduleKey, offTimeout);
            ClasspathResult offlineResult = generateClasspathForModule(projectRoot, cacheFile, mvnExec,
                    config.withOffline(true), offTimeout, projectSelector, progress);
            if (offlineResult.isAvailable() && offlineResult.hasValidJars()) {
                saveCacheMetadata(metaFile, moduleIndex, config);
                log.info("[CLASSPATH] Module {}: offline succeeded ({} jars)", moduleKey, offlineResult.getJars().size());
                return offlineResult;
            }
            log.warn("[CLASSPATH] Module {}: offline failed", moduleKey);
        }

        // Step D: stale cache（元数据不匹配但文件仍在）
        if (Files.exists(cacheFile)) {
            ClasspathResult stale = readClasspathFile(cacheFile, "cache-stale-" + moduleKey);
            stale.setFallback(true);
            warningsFor(stale).add("Using stale cache for module: " + moduleKey);
            log.warn("[CLASSPATH] Module {}: using stale cache ({} jars)", moduleKey, stale.getJars().size());
            return stale;
        }

        // Step E: source-only fallback
        return fallbackToSourceOnly(moduleKey);
    }

    /**
     * source-only 降级。
     */
    private ClasspathResult fallbackToSourceOnly(String moduleKey) {
        log.warn("[CLASSPATH] Module {}: all strategies failed, source-only analysis", moduleKey);
        return ClasspathResult.unavailable("No classpath for " + moduleKey + "; source-only analysis");
    }

    /**
     * 执行 {@code mvn install -DskipTests -q} 准备 reactor 内部模块。
     */
    private boolean runMvnInstall(Path workDir, String mvnExec, long timeoutSeconds,
                                  AnalysisProgressListener progress) {
        List<String> cmd = new ArrayList<>();
        cmd.add(mvnExec);
        cmd.add("install");
        cmd.add("-DskipTests");
        cmd.add("-q");
        cmd.add("-o"); // 快速安装，不需要联网

        log.info("[CLASSPATH] Preparing reactor: {}", String.join(" ", cmd));
        progress.onEvent("classpath", "INFO", "Preparing reactor artifacts: mvn install -DskipTests");

        try {
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.directory(workDir.toFile());
            pb.redirectErrorStream(true);
            Process process = pb.start();

            // 在后台线程消费 stdout，避免管道缓冲区满导致死锁
            StringBuilder outputCapture = new StringBuilder();
            Thread outputReader = new Thread(() -> {
                try (var reader = new BufferedReader(
                        new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (outputCapture.length() < MAVEN_OUTPUT_TAIL_CHARS * 2) {
                            outputCapture.append(line).append("\n");
                        }
                    }
                } catch (IOException ignored) {
                    // 进程退出后管道关闭，正常行为
                }
            }, "mvn-install-reader");
            outputReader.setDaemon(true);
            outputReader.start();

            boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                outputReader.interrupt();
                log.warn("[CLASSPATH] Reactor install timed out after {}s", timeoutSeconds);
                return false;
            }
            try { outputReader.join(1000); } catch (InterruptedException ignored) {}

            int exitCode = process.exitValue();
            if (exitCode != 0) {
                String tail = outputCapture.toString();
                if (tail.length() > MAVEN_OUTPUT_TAIL_CHARS) {
                    tail = tail.substring(tail.length() - MAVEN_OUTPUT_TAIL_CHARS);
                }
                log.warn("[CLASSPATH] Reactor install failed with exit code {}; tail: {}",
                        exitCode, tail);
                return false;
            }
            log.info("[CLASSPATH] Reactor install completed successfully");
            return true;
        } catch (IOException | InterruptedException e) {
            log.warn("[CLASSPATH] Reactor install failed: {}", e.getMessage());
            return false;
        }
    }

    // ====== 缓存元数据 ======

    /**
     * 缓存元数据，用于校验缓存有效性。
     */
    private record CacheMetadata(String pomHash, String settingsHash, String jdkVersion, String createdAt) {
        boolean isValid(String currentPomHash, String currentSettingsHash, String currentJdkVersion) {
            return pomHash.equals(currentPomHash)
                    && Objects.equals(settingsHash, currentSettingsHash)
                    && jdkVersion.equals(currentJdkVersion);
        }

        static CacheMetadata read(Path metaFile) {
            try {
                String content = Files.readString(metaFile, StandardCharsets.UTF_8).trim();
                // Simple line-based format: key=value
                String pomHash = "";
                String settingsHash = "";
                String jdkVersion = "";
                String createdAt = "";
                for (String line : content.split("\n")) {
                    line = line.trim();
                    if (line.startsWith("pomHash=")) {
                        pomHash = line.substring(8);
                    } else if (line.startsWith("settingsHash=")) {
                        settingsHash = line.substring(13);
                    } else if (line.startsWith("jdkVersion=")) {
                        jdkVersion = line.substring(11);
                    } else if (line.startsWith("createdAt=")) {
                        createdAt = line.substring(10);
                    }
                }
                return new CacheMetadata(pomHash, settingsHash, jdkVersion, createdAt);
            } catch (IOException e) {
                return null;
            }
        }

        void write(Path metaFile) {
            try {
                String content = String.format(
                        "pomHash=%s\nsettingsHash=%s\njdkVersion=%s\ncreatedAt=%s\n",
                        pomHash, settingsHash, jdkVersion, createdAt);
                Files.writeString(metaFile, content, StandardCharsets.UTF_8);
            } catch (IOException e) {
                // Non-fatal; cache will be regenerated next time
            }
        }
    }

    private String toMetaFileName(String moduleKey) {
        return toCacheFileName(moduleKey).replace(".txt", ".meta");
    }

    private boolean isCacheValid(Path metaFile, MavenModuleIndex moduleIndex, MavenConfig config) {
        if (!Files.exists(metaFile)) {
            return false;
        }
        CacheMetadata meta = CacheMetadata.read(metaFile);
        if (meta == null) {
            return false;
        }

        String currentPomHash = computePomHash(moduleIndex.getRootPom());
        String currentSettingsHash = computeSettingsHash(config.getSettingsXml());
        String currentJdk = getJdkVersion();

        return meta.isValid(currentPomHash, currentSettingsHash, currentJdk);
    }

    private void saveCacheMetadata(Path metaFile, MavenModuleIndex moduleIndex, MavenConfig config) {
        String pomHash = computePomHash(moduleIndex.getRootPom());
        String settingsHash = computeSettingsHash(config.getSettingsXml());
        String jdkVersion = getJdkVersion();
        String createdAt = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        new CacheMetadata(pomHash, settingsHash, jdkVersion, createdAt).write(metaFile);
    }

    private String computePomHash(Path rootPom) {
        if (rootPom == null || !Files.exists(rootPom)) {
            return "";
        }
        try {
            byte[] content = Files.readAllBytes(rootPom);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(content);
            return HexFormat.of().formatHex(hash);
        } catch (IOException | NoSuchAlgorithmException e) {
            return "";
        }
    }

    private String computeSettingsHash(String settingsXmlPath) {
        if (settingsXmlPath == null || settingsXmlPath.isEmpty()) {
            return "";
        }
        Path settingsFile = Paths.get(settingsXmlPath);
        if (!Files.exists(settingsFile)) {
            return "";
        }
        try {
            byte[] content = Files.readAllBytes(settingsFile);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(content);
            return HexFormat.of().formatHex(hash);
        } catch (IOException | NoSuchAlgorithmException e) {
            return "";
        }
    }

    private String getJdkVersion() {
        return System.getProperty("java.version", "unknown");
    }

    /**
     * 带目标模块选择的 classpath 生成（{@code -pl :artifactId -am}）。
     */
    ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                MavenConfig config, long timeoutSeconds, String targetModule) {
        return generateClasspathForModule(workDir, outputFile, mvnExec, config, timeoutSeconds, targetModule,
                AnalysisProgressListener.NOOP);
    }

    ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                MavenConfig config, long timeoutSeconds, String targetModule,
                                                AnalysisProgressListener progress) {
        List<String> cmd = new ArrayList<>();
        cmd.add(mvnExec);

        if (targetModule != null && !targetModule.isEmpty()) {
            cmd.add("-pl");
            cmd.add(targetModule);
            cmd.add("-am");
        }
        cmd.add("org.apache.maven.plugins:maven-dependency-plugin:" + config.getDependencyPluginVersion() + ":build-classpath");

        cmd.add("-Dmdep.outputFile=" + outputFile.toAbsolutePath());
        cmd.add("-DincludeScope=compile");

        if (config.getSettingsXml() != null && !config.getSettingsXml().isEmpty()) {
            cmd.add("-s");
            cmd.add(config.getSettingsXml());
        }
        if (config.getLocalRepository() != null && !config.getLocalRepository().isEmpty()) {
            cmd.add("-Dmaven.repo.local=" + config.getLocalRepository());
        }
        if (config.isOffline()) {
            cmd.add("-o");
        }

        return executeMaven(workDir, outputFile, mvnExec, config, cmd, timeoutSeconds, progress);
    }

    private ClasspathResult executeMaven(Path workDir, Path outputFile, String mvnExec,
                                          MavenConfig config, List<String> cmd, long timeoutSeconds,
                                          AnalysisProgressListener progress) {
        String commandLine = String.join(" ", cmd);
        log.info("[CLASSPATH] Executing: {}", commandLine);
        progress.onEvent("classpath", "INFO", "Executing Maven classpath command: " + commandLine);

        try {
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.directory(workDir.toFile());
            pb.redirectErrorStream(false);

            long started = System.nanoTime();
            Process process = pb.start();
            CompletableFuture<String> stdoutFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getInputStream(), "stdout", progress));
            CompletableFuture<String> stderrFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getErrorStream(), "stderr", progress));
            boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
            long durationMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);

            if (!finished) {
                process.destroyForcibly();
                String stdout = awaitOutput(stdoutFuture);
                String stderr = awaitOutput(stderrFuture);
                ClasspathResult result = fail("Maven classpath generation timed out after " + timeoutSeconds + "s",
                        commandLine);
                result.setDurationMs(durationMs);
                result.setStdoutTail(tail(stdout));
                result.setStderrTail(tail(stderr));
                result.setTimedOut(true);
                progress.onEvent("classpath", "ERROR", "Maven classpath generation timed out after "
                        + timeoutSeconds + "s");
                return result;
            }

            int exitCode = process.exitValue();
            String stdout = awaitOutput(stdoutFuture);
            String stderr = awaitOutput(stderrFuture);
            if (exitCode != 0) {
                ClasspathResult result = fail("Maven exited with code " + exitCode + ": " + tail(stderr),
                        commandLine, exitCode);
                result.setDurationMs(durationMs);
                result.setStdoutTail(tail(stdout));
                result.setStderrTail(tail(stderr));
                progress.onEvent("classpath", "ERROR", "Maven exited with code " + exitCode);
                return result;
            }

            if (!Files.exists(outputFile)) {
                ClasspathResult result = fail("Maven completed but classpath file was not created", commandLine, exitCode);
                result.setDurationMs(durationMs);
                result.setStdoutTail(tail(stdout));
                result.setStderrTail(tail(stderr));
                return result;
            }

            String mode = config.isOffline() ? "offline-" : "online-";
            String wrapper = mvnExec.endsWith("mvnw.cmd") || mvnExec.endsWith("mvnw") ? "wrapper" : "system";
            ClasspathResult result = readClasspathFile(outputFile, "maven-" + mode + wrapper);
            result.setGenerated(true);
            result.setCommand(commandLine);
            result.setExitCode(exitCode);
            result.setDurationMs(durationMs);
            result.setStdoutTail(tail(stdout));
            result.setStderrTail(tail(stderr));
            log.info("[CLASSPATH] Classpath generated: {} jars in {}ms", result.getJars().size(), durationMs);
            progress.onEvent("classpath", "INFO", "Classpath generated: " + result.getJars().size()
                    + " jars in " + durationMs + "ms");
            return result;

        } catch (IOException e) {
            return fail("Maven execution failed: " + e.getMessage(), commandLine);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return fail("Maven execution interrupted", commandLine);
        }
    }

    private static List<String> warningsFor(ClasspathResult result) {
        if (result.getWarnings() == null || !(result.getWarnings() instanceof ArrayList)) {
            result.setWarnings(new ArrayList<>(result.getWarnings() != null ? result.getWarnings() : List.of()));
        }
        return result.getWarnings();
    }

    /**
     * 探测 Maven 可执行文件路径。
     * 优先级：mvnw.cmd → mvnw → config.executable → MAVEN_HOME → M2_HOME → 同级目录扫描 → PATH
     *
     * <p>检测到 Maven 4.x 时自动跳过，寻找 Maven 3.x。
     */
    String detectMavenExecutable(Path sourcePath, MavenConfig config) {
        // 1. 项目级 Wrapper
        Path mvnwCmd = sourcePath.resolve("mvnw.cmd");
        if (Files.exists(mvnwCmd) && Files.isRegularFile(mvnwCmd)) {
            String candidate = mvnwCmd.toAbsolutePath().toString();
            if (isMaven3x(candidate)) {
                return candidate;
            }
            log.warn("mvnw.cmd uses Maven 4+, skipped");
        }
        Path mvnw = sourcePath.resolve("mvnw");
        if (Files.exists(mvnw) && Files.isRegularFile(mvnw)) {
            String candidate = mvnw.toAbsolutePath().toString();
            if (isMaven3x(candidate)) {
                return candidate;
            }
            log.warn("mvnw uses Maven 4+, skipped");
        }

        // 2. 用户显式指定
        if (config.getExecutable() != null && !config.getExecutable().isEmpty()) {
            return config.getExecutable();
        }

        // 3. MAVEN_HOME — 检测到 4.x 时同级目录扫描
        String mavenHome = getEnv("MAVEN_HOME");
        if (mavenHome != null) {
            String candidate = findMvnInDir(Paths.get(mavenHome));
            if (candidate != null) {
                if (isMaven3x(candidate)) {
                    return candidate;
                }
                log.warn("MAVEN_HOME points to Maven 4+ ({}), scanning sibling directories", mavenHome);
                String mvn3 = findMaven3InSiblingDirs(Paths.get(mavenHome).getParent());
                if (mvn3 != null) {
                    return mvn3;
                }
            }
        }

        // 4. M2_HOME
        String m2Home = getEnv("M2_HOME");
        if (m2Home != null) {
            String candidate = findMvnInDir(Paths.get(m2Home));
            if (candidate != null) {
                if (isMaven3x(candidate)) {
                    return candidate;
                }
                String mvn3 = findMaven3InSiblingDirs(Paths.get(m2Home).getParent());
                if (mvn3 != null) {
                    return mvn3;
                }
            }
        }

        // 5. 如果 MAVEN_HOME 未找到有效版本，搜索其同级目录作为兜底
        if (mavenHome != null) {
            Path parent = Paths.get(mavenHome).getParent();
            if (parent != null) {
                String mvn3 = findMaven3InSiblingDirs(parent);
                if (mvn3 != null) {
                    return mvn3;
                }
            }
        }

        // 6. PATH — 优先找 Maven 3.x
        String pathMvnCmd = findOnPath("mvn.cmd");
        if (pathMvnCmd != null && isMaven3x(pathMvnCmd)) {
            return pathMvnCmd;
        }
        String pathMvn = findOnPath("mvn");
        if (pathMvn != null && isMaven3x(pathMvn)) {
            return pathMvn;
        }

        // 7. 兜底：优先 PATH 上的 mvn
        if (pathMvnCmd != null) {
            return pathMvnCmd;
        }
        if (pathMvn != null) {
            return pathMvn;
        }

        // 8. 最后兜底：MAVEN_HOME 的 Maven（即使是 4.x，尝试运行，失败则降级）
        if (mavenHome != null) {
            String candidate = findMvnInDir(Paths.get(mavenHome));
            if (candidate != null) {
                log.warn("No Maven 3.x found, falling back to {} (may fail)", candidate);
                return candidate;
            }
        }
        return null;
    }

    /**
     * 在指定 Maven 安装目录下查找 {@code bin/mvn.cmd} 或 {@code bin/mvn}。
     */
    private String findMvnInDir(Path homeDir) {
        if (homeDir == null || !Files.isDirectory(homeDir)) {
            return null;
        }
        Path mvn = homeDir.resolve("bin/mvn.cmd");
        if (Files.exists(mvn) && Files.isRegularFile(mvn)) {
            return mvn.toAbsolutePath().toString();
        }
        mvn = homeDir.resolve("bin/mvn");
        if (Files.exists(mvn) && Files.isRegularFile(mvn)) {
            return mvn.toAbsolutePath().toString();
        }
        return null;
    }

    /**
     * 在 Maven 发行版同级目录中扫描 Maven 3.x 安装。
     * 例如 MAVEN_HOME 为 {@code /opt/maven/apache-maven-4.0.0} 时，扫描 {@code /opt/maven/} 下所有子目录。
     */
    private String findMaven3InSiblingDirs(Path parentDir) {
        if (parentDir == null || !Files.isDirectory(parentDir)) {
            return null;
        }
        try (Stream<Path> dirs = Files.list(parentDir)) {
            return dirs
                    .filter(Files::isDirectory)
                    .map(this::findMvnInDir)
                    .filter(Objects::nonNull)
                    .filter(this::isMaven3x)
                    .findFirst()
                    .orElse(null);
        } catch (IOException e) {
            log.warn("Failed to scan Maven sibling directories in {}: {}", parentDir, e.getMessage());
            return null;
        }
    }

    /**
     * 运行 {@code mvn --version} 并解析 Maven 主版本号。
     *
     * @return 版本号如 {@code "3.8.8"}，解析失败返回 {@code null}
     */
    private String getMavenVersion(String executable) {
        try {
            ProcessBuilder pb = new ProcessBuilder(executable, "--version");
            Process process = pb.start();
            boolean finished = process.waitFor(10, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                return null;
            }
            String output = readStream(process.getInputStream());
            for (String line : output.split("\n")) {
                line = line.trim();
                if (line.startsWith("Apache Maven ")) {
                    String rest = line.substring("Apache Maven ".length()).trim();
                    int space = rest.indexOf(' ');
                    return space > 0 ? rest.substring(0, space) : rest;
                }
            }
            return null;
        } catch (Exception e) {
            log.debug("Failed to get Maven version for {}: {}", executable, e.getMessage());
            return null;
        }
    }

    /**
     * 检查 Maven 可执行文件是否为 3.x 版本。
     */
    private boolean isMaven3x(String executable) {
        String version = getMavenVersion(executable);
        if (version == null) {
            return false;
        }
        if (!version.startsWith("3.")) {
            log.info("Maven version {} detected at {}, searching for 3.x", version, executable);
            return false;
        }
        return true;
    }

    /**
     * 通过 {@code mvnw.cmd dependency:build-classpath} 生成 classpath（旧接口，委托新方法）。
     *
     * @param timeoutSeconds 超时秒数（离线 60s，联网 600s）
     */
    ClasspathResult generateClasspath(Path sourcePath, String mvnExec, MavenConfig config, long timeoutSeconds) {
        return generateClasspath(sourcePath, mvnExec, config, timeoutSeconds, AnalysisProgressListener.NOOP);
    }

    ClasspathResult generateClasspath(Path sourcePath, String mvnExec, MavenConfig config, long timeoutSeconds,
                                      AnalysisProgressListener progress) {
        Path outputDir = sourcePath.resolve(".argus");
        try {
            Files.createDirectories(outputDir);
        } catch (IOException e) {
            List<String> cmd = new ArrayList<>();
            cmd.add(mvnExec);
            cmd.add("dependency:build-classpath");
            return fail("Failed to create .argus directory: " + e.getMessage(), cmd);
        }
        Path outputFile = outputDir.resolve("classpath.txt");
        return generateClasspathForModule(sourcePath, outputFile, mvnExec, config, timeoutSeconds, null, progress);
    }

    /**
     * 从 classpath 文本文件读取 JAR 路径列表。
     * Windows 使用分号分隔，Linux/macOS 使用冒号分隔。
     */
    ClasspathResult readClasspathFile(Path classpathFile, String source) {
        try {
            String content = Files.readString(classpathFile, StandardCharsets.UTF_8).trim();
            if (content.isEmpty()) {
                return new ClasspathResult(false, false, true, List.of(), source,
                        List.of("Classpath file is empty: " + classpathFile),
                        List.of(), null, null);
            }

            String separator = content.contains(";") ? ";" : ":";
            String[] parts = content.split(separator);
            List<String> validJars = new ArrayList<>();
            List<String> warnings = new ArrayList<>();

            for (String part : parts) {
                String jarPath = part.trim();
                if (jarPath.isEmpty()) {
                    continue;
                }
                if (Files.exists(Paths.get(jarPath))) {
                    validJars.add(jarPath);
                } else {
                    warnings.add("JAR not found, skipping: " + jarPath);
                }
            }

            return new ClasspathResult(true, false, false, validJars, source,
                    warnings, List.of(), null, null);

        } catch (IOException e) {
            return new ClasspathResult(false, false, true, List.of(), source,
                    List.of("Failed to read classpath file: " + e.getMessage()),
                    List.of(e.getMessage()), null, null);
        }
    }

    private ClasspathResult fail(String reason, List<String> cmd) {
        return fail(reason, String.join(" ", cmd), null);
    }

    private ClasspathResult fail(String reason, String commandLine) {
        return fail(reason, commandLine, null);
    }

    private ClasspathResult fail(String reason, String commandLine, Integer exitCode) {
        return new ClasspathResult(false, false, true, List.of(), "none",
                List.of(reason), List.of(reason), commandLine, exitCode);
    }

    private String getEnv(String name) {
        try {
            return System.getenv(name);
        } catch (Exception e) {
            return null;
        }
    }

    private String findOnPath(String name) {
        String pathEnv = getEnv("PATH");
        if (pathEnv == null) {
            return null;
        }
        for (String dir : pathEnv.split(";")) {
            Path candidate = Paths.get(dir.trim(), name);
            if (Files.exists(candidate)) {
                return candidate.toAbsolutePath().toString();
            }
        }
        return null;
    }

    private String readStream(InputStream stream) {
        return readStream(stream, null, AnalysisProgressListener.NOOP);
    }

    private String readStream(InputStream stream, String streamName, AnalysisProgressListener progress) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                if (!sb.isEmpty()) {
                    sb.append("\n");
                }
                sb.append(line);
                if (streamName != null && shouldLogMavenLine(line)) {
                    log.info("[CLASSPATH][MAVEN {}] {}", streamName, line);
                    progress.onEvent("classpath", "INFO", streamName + ": " + line);
                }
            }
            return sb.toString();
        } catch (IOException e) {
            return "(failed to read stream: " + e.getMessage() + ")";
        }
    }

    private String awaitOutput(CompletableFuture<String> outputFuture) {
        try {
            return outputFuture.get(5, TimeUnit.SECONDS);
        } catch (Exception e) {
            return "(failed to collect Maven output: " + e.getMessage() + ")";
        }
    }

    private String tail(String value) {
        if (value == null || value.length() <= MAVEN_OUTPUT_TAIL_CHARS) {
            return value;
        }
        return value.substring(value.length() - MAVEN_OUTPUT_TAIL_CHARS);
    }

    private boolean shouldLogMavenLine(String line) {
        if (line == null || line.isBlank()) {
            return false;
        }
        return line.contains("[ERROR]")
                || line.contains("[WARNING]")
                || line.contains("[INFO] Building")
                || line.contains("[INFO] Reactor")
                || line.contains("[INFO] BUILD")
                || line.contains("Downloading")
                || line.contains("Downloaded");
    }

    private String toCacheFileName(String moduleKey) {
        return moduleKey.replace('\\', '/')
                .replaceAll("^\\./", "")
                .replace("/", "__")
                .replace(':', '_') + ".txt";
    }

    private String toMavenProjectSelector(String requestedSelector, MavenModule module) {
        String normalizedRequested = requestedSelector != null ? requestedSelector.replace('\\', '/') : "";
        if (module.getModulePath() != null && module.getModulePath().equals(normalizedRequested)) {
            return module.getModulePath();
        }
        return ":" + module.getArtifactId();
    }

}
