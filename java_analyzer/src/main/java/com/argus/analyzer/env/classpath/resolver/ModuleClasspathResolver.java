package com.argus.analyzer.env.classpath.resolver;

import com.argus.analyzer.env.ClasspathMode;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModule;
import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.classpath.cache.ClasspathCacheManager;
import com.argus.analyzer.env.classpath.gateway.ClasspathGateway;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Handles module-aware classpath resolution for multi-module Maven projects.
 */
@Component
public class ModuleClasspathResolver {

    private static final Logger log = LoggerFactory.getLogger(ModuleClasspathResolver.class);
    private static final String CACHE_DIR = ".argus/classpath";

    private final ClasspathGateway gateway;
    private final ClasspathCacheManager cacheManager;

    public ModuleClasspathResolver(ClasspathGateway gateway, ClasspathCacheManager cacheManager) {
        this.gateway = gateway;
        this.cacheManager = cacheManager;
    }

    public ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules, MavenConfig config) {
        return resolve(moduleIndex, targetModules, config, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules, MavenConfig config,
                                   AnalysisProgressListener progress) {
        if (targetModules == null || targetModules.isEmpty()) {
            log.info("[CLASSPATH] No target modules specified");
            return ClasspathResult.unavailable("No target modules specified");
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
        Path cacheFile = cacheDir.resolve(cacheManager.toCacheFileName(moduleKey));
        Path metaFile = cacheDir.resolve(cacheManager.toMetaFileName(moduleKey));

        ClasspathMode mode = config.getClasspathMode();
        log.info("[CLASSPATH] Module {}: classpathMode={}", moduleKey, mode);

        if (mode == ClasspathMode.SOURCE_ONLY) {
            log.info("[CLASSPATH] Module {}: SOURCE_ONLY mode, skipping classpath", moduleKey);
            return ClasspathResult.unavailable("classpathMode=SOURCE_ONLY");
        }

        // Step A: per-module cache（带元数据校验）
        log.info("[CLASSPATH] Module {}: checking cache at {}", moduleKey, cacheFile);
        if (Files.exists(cacheFile)) {
            ClasspathResult cached = gateway.readClasspathFile(cacheFile, "cache-" + moduleKey);
            if (cached.hasValidJars()) {
                if (cacheManager.isCacheValid(metaFile, moduleIndex, config)) {
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

        String mvnExec = gateway.detectMavenExecutable(projectRoot, config);
        if (mvnExec == null) {
            log.warn("[CLASSPATH] Module {}: no Maven executable found", moduleKey);
            return fallbackToSourceOnly(moduleKey);
        }

        try {
            Files.createDirectories(cacheDir);
        } catch (IOException e) {
            log.warn("[CLASSPATH] Module {}: failed to create cache dir: {}", moduleKey, e.getMessage());
            return fallbackToSourceOnly(moduleKey);
        }

        if (config.isPrepareReactorArtifacts()) {
            log.info("[CLASSPATH] Module {}: preparing reactor artifacts (mvn install -DskipTests)", moduleKey);
            boolean prepared = gateway.runMvnInstall(projectRoot, mvnExec, config.getOnlineTimeoutSeconds(), progress);
            if (!prepared) {
                log.warn("[CLASSPATH] Module {}: reactor artifact preparation failed, continuing anyway", moduleKey);
            }
        }

        String projectSelector = toMavenProjectSelector(moduleSelector, module);

        boolean tryOnlineFirst = !config.isOffline();

        if (tryOnlineFirst) {
            long onTimeout = config.getOnlineTimeoutSeconds();
            log.info("[CLASSPATH] Module {}: online generation (timeout={}s)", moduleKey, onTimeout);
            ClasspathResult onlineResult = gateway.generateClasspathForModule(projectRoot, cacheFile, mvnExec,
                    config.withOffline(false), onTimeout, projectSelector, progress);
            if (onlineResult.isAvailable() && onlineResult.hasValidJars()) {
                cacheManager.saveCacheMetadata(metaFile, moduleIndex, config);
                log.info("[CLASSPATH] Module {}: online succeeded ({} jars)", moduleKey, onlineResult.getJars().size());
                return onlineResult;
            }
            log.warn("[CLASSPATH] Module {}: online failed", moduleKey);
        }

        long offTimeout = config.getOfflineTimeoutSeconds();
        log.info("[CLASSPATH] Module {}: offline generation (timeout={}s)", moduleKey, offTimeout);
        ClasspathResult offlineResult = gateway.generateClasspathForModule(projectRoot, cacheFile, mvnExec,
                config.withOffline(true), offTimeout, projectSelector, progress);
        if (offlineResult.isAvailable() && offlineResult.hasValidJars()) {
            cacheManager.saveCacheMetadata(metaFile, moduleIndex, config);
            log.info("[CLASSPATH] Module {}: offline succeeded ({} jars)", moduleKey, offlineResult.getJars().size());
            return offlineResult;
        }
        log.warn("[CLASSPATH] Module {}: offline failed", moduleKey);

        if (Files.exists(cacheFile)) {
            ClasspathResult stale = gateway.readClasspathFile(cacheFile, "cache-stale-" + moduleKey);
            stale.setFallback(true);
            stale.addWarning("Using stale cache for module: " + moduleKey);
            log.warn("[CLASSPATH] Module {}: using stale cache ({} jars)", moduleKey, stale.getJars().size());
            return stale;
        }

        return fallbackToSourceOnly(moduleKey);
    }

    private ClasspathResult fallbackToSourceOnly(String moduleKey) {
        log.warn("[CLASSPATH] Module {}: all strategies failed, source-only analysis", moduleKey);
        return ClasspathResult.unavailable("No classpath for " + moduleKey + "; source-only analysis");
    }

    private String toMavenProjectSelector(String requestedSelector, MavenModule module) {
        String normalizedRequested = requestedSelector != null ? requestedSelector.replace('\\', '/') : "";
        if (module.getModulePath() != null && module.getModulePath().equals(normalizedRequested)) {
            return module.getModulePath();
        }
        return ":" + module.getArtifactId();
    }
}
