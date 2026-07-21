package com.argus.analyzer.env.classpath.resolver;

import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.classpath.gateway.ClasspathGateway;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Handles legacy single-module classpath resolution.
 *
 * <p>6-step priority chain:
 * <ol>
 *   <li>User-specified explicit classpath file</li>
 *   <li>Cache file {@code .argus/classpath.txt} — return directly if valid JARs exist</li>
 *   <li>Offline Maven generation ({@code -o}, short timeout)</li>
 *   <li>Online Maven generation (long timeout)</li>
 *   <li>Stale cache — try to use even if JARs are missing</li>
 *   <li>Fallback to source-only analysis</li>
 * </ol>
 */
@Component
public class LegacyClasspathResolver {

    private static final Logger log = LoggerFactory.getLogger(LegacyClasspathResolver.class);
    private static final String CACHE_FILE = ".argus/classpath.txt";

    private final ClasspathGateway gateway;

    public LegacyClasspathResolver(ClasspathGateway gateway) {
        this.gateway = gateway;
    }

    public ClasspathResult resolve(Path sourcePath, MavenConfig config) {
        return resolve(sourcePath, config, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult resolve(Path sourcePath, MavenConfig config, AnalysisProgressListener progress) {
        // 1. 用户显式传入 classpath 文件
        if (config.getClasspathFile() != null && !config.getClasspathFile().isEmpty()) {
            Path cpFile = sourcePath.resolve(config.getClasspathFile());
            if (Files.exists(cpFile)) {
                ClasspathResult result = gateway.readClasspathFile(cpFile, "explicit");
                log.info("[CLASSPATH] Step 0: explicit file — loaded {} jars from {}", result.getJars().size(), cpFile);
                return result;
            }
            log.warn("[CLASSPATH] Step 0: explicit file not found: {}", cpFile);
        }

        // 2. 缓存文件
        Path cachedFile = sourcePath.resolve(CACHE_FILE);
        boolean cacheFileExists = Files.exists(cachedFile);
        log.info("[CLASSPATH] Step A: checking cache at {} ... exists={}", cachedFile, cacheFileExists);
        ClasspathResult cacheResult = cacheFileExists ? gateway.readClasspathFile(cachedFile, "cache") : null;

        if (cacheResult != null && cacheResult.hasValidJars()) {
            log.info("[CLASSPATH] Step A: cache hit — {} valid jars, using directly", cacheResult.getJars().size());
            return cacheResult;
        }
        log.info("[CLASSPATH] Step A: cache skipped ({}), proceeding to Maven generation",
                cacheResult != null ? "hasValidJars=false" : "file not found");

        // 3/4. 自动 Maven 生成
        if (config.isAutoDetect() && config.isGenerateClasspath()) {
            String mvnExec = gateway.detectMavenExecutable(sourcePath, config);
            if (mvnExec != null) {
                // 3. 离线模式
                long offlineTimeout = config.getOfflineTimeoutSeconds();
                log.info("[CLASSPATH] Step B: starting offline Maven generation (timeout={}s) ...", offlineTimeout);
                MavenConfig offlineConfig = config.withOffline(true);
                ClasspathResult offlineResult = gateway.generateClasspath(sourcePath, mvnExec, offlineConfig, offlineTimeout, progress);
                if (offlineResult.isAvailable()) {
                    log.info("[CLASSPATH] Step B: offline Maven succeeded — {} jars", offlineResult.getJars().size());
                    return offlineResult;
                }
                log.warn("[CLASSPATH] Step B: offline Maven failed — {}", offlineResult.getErrors());

                // 4. 联网模式
                long onlineTimeout = config.getOnlineTimeoutSeconds();
                log.info("[CLASSPATH] Step C: starting online Maven generation (timeout={}s) ...", onlineTimeout);
                MavenConfig onlineConfig = config.withOffline(false);
                ClasspathResult onlineResult = gateway.generateClasspath(sourcePath, mvnExec, onlineConfig, onlineTimeout, progress);
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

        // 5. 陈旧缓存
        if (cacheResult != null) {
            log.info("[CLASSPATH] Step D: using stale cache — {} jars (may be incomplete)", cacheResult.getJars().size());
            cacheResult.setFallback(true);
            cacheResult.setSource("cache-stale");
            cacheResult.addWarning("Using stale cache — some or all JARs may be missing");
            return cacheResult;
        }
        log.info("[CLASSPATH] Step D: no stale cache available");

        // 6. 全部失败，降级
        log.warn("[CLASSPATH] Step E: all steps failed, falling back to source-only analysis");
        return ClasspathResult.unavailable("No classpath available; fallback to source-only analysis");
    }
}
