package com.argus.analyzer.service;

import com.argus.analyzer.application.AnalysisPlan;
import com.argus.analyzer.application.ClasspathResolver;
import com.argus.analyzer.application.PassExecutor;
import com.argus.analyzer.application.PlanRegistry;
import com.argus.analyzer.domain.AnalysisCommand;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.AnalysisScope;
import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModule;
import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.ModuleClassifier;
import com.argus.analyzer.support.ProjectIndexCache;
import com.argus.analyzer.support.SourceFileScanner;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 白盒分析编排（应用层）。
 *
 * <p>入口接收已由 HTTP adapter 映射的不可变 {@link AnalysisCommand}（携带
 * real-path 边界校验后的源码路径），不再读取 HTTP DTO 或比较字符串 scope。
 * 核心流程：解析模块上下文 → 按 scope 选择 {@link AnalysisPlan} → 由
 * {@link PassExecutor} 按能力依赖并行/串行执行 pass → 合并 diagnostics。</p>
 */
@Service
public class ProjectAnalyzerService {

    private static final Logger log = LoggerFactory.getLogger(ProjectAnalyzerService.class);

    private final PlanRegistry planRegistry;
    private final PassExecutor passExecutor;
    private final ProjectIndexCache indexCache;
    private final ClasspathResolver classpathResolver;
    private final SourceFileScanner sourceFileScanner;
    private final ModuleClassifier moduleClassifier;

    public ProjectAnalyzerService(PlanRegistry planRegistry,
                                  PassExecutor passExecutor,
                                  ProjectIndexCache indexCache,
                                  ClasspathResolver classpathResolver,
                                  SourceFileScanner sourceFileScanner,
                                  ModuleClassifier moduleClassifier) {
        this.planRegistry = planRegistry;
        this.passExecutor = passExecutor;
        this.indexCache = indexCache;
        this.classpathResolver = classpathResolver;
        this.sourceFileScanner = sourceFileScanner;
        this.moduleClassifier = moduleClassifier;
    }

    public AnalysisResult analyze(AnalysisCommand command, MavenConfig mavenConfig,
                                  AnalysisProgressListener progress) {
        // fail-closed：real-path/allowed-roots 边界校验已在 HTTP adapter 完成，
        // 此处命令携带的 sourcePath 即已校验的 real path。
        MavenConfig maven = mavenConfig != null ? mavenConfig : new MavenConfig();
        var cacheKey = indexCache.createKey(command, maven);
        var cached = indexCache.getOrCompute(cacheKey, () -> analyzeUncached(command, maven, progress));
        if (cached.cacheHit()) {
            progress.onEvent("cache", "INFO", "Analysis result loaded from cache");
        }
        return cached.response();
    }

    private AnalysisResult analyzeUncached(AnalysisCommand command, MavenConfig mavenConfig,
                                           AnalysisProgressListener progress) {
        // 模块索引 + classpath 解析（P0-P1）
        ModuleContext ctx = resolveModuleContext(command, mavenConfig, progress);

        // 按 scope 选择 pass 计划，交给 PassExecutor 按能力依赖编排执行
        AnalysisPlan plan = planRegistry.planFor(command.scope());
        AnalysisContext context = new AnalysisContext(command.sourcePath(), command,
                ctx.classpathJars(), progress);
        AnalysisResult result = passExecutor.execute(plan.passes(), context);

        // 合并 classpath / 模块上下文诊断
        enrichDiagnostics(result.diagnostics(), ctx);
        logSummary(command.scope(), result);
        return result;
    }

    // ====== 模块上下文解析 ======

    private record ModuleContext(
            MavenModuleIndex index,
            List<String> targetModules,
            List<Path> classpathJars,
            ClasspathResult cpResult) {
    }

    private ModuleContext resolveModuleContext(AnalysisCommand command, MavenConfig mavenConfig,
                                               AnalysisProgressListener progress) {
        Path sourcePath = command.sourcePath();
        MavenModuleIndex moduleIndex = sourceFileScanner.getCurrentModuleIndex(sourcePath);
        if (moduleIndex != null) {
            log.info("[POM] Module index built: {} modules, rootPom={}",
                    moduleIndex.getModuleCount(), moduleIndex.getRootPom());
        } else {
            log.info("[POM] No Maven module index (non-Maven project or scan failed)");
        }

        List<String> targetModules = resolveTargetModules(command.targetModules(), moduleIndex, progress);

        ClasspathResult cpResult = moduleIndex != null && targetModules != null && !targetModules.isEmpty()
                ? classpathResolver.resolve(moduleIndex, targetModules, mavenConfig, progress)
                : classpathResolver.resolve(sourcePath, mavenConfig, progress);

        List<Path> classpathJars = cpResult.isAvailable()
                ? cpResult.getJars().stream().map(Path::of).toList()
                : List.of();

        log.info("Classpath: available={} source={} jars={}",
                cpResult.isAvailable(), cpResult.getSource(), cpResult.getJars().size());

        return new ModuleContext(moduleIndex, targetModules, classpathJars, cpResult);
    }

    private List<String> resolveTargetModules(List<String> explicitTargets, MavenModuleIndex moduleIndex,
                                              AnalysisProgressListener progress) {
        if (explicitTargets != null && !explicitTargets.isEmpty()) return explicitTargets;
        if (moduleIndex == null) return null;
        log.info("[AUTO_DETECT] No target modules specified, running classification...");
        moduleClassifier.classifyAll(moduleIndex, progress);
        var targets = moduleClassifier.selectTargets(moduleIndex, progress);
        var result = targets.stream().map(MavenModule::getDisplayName).toList();
        log.info("[AUTO_DETECT] Selected {} target modules: {}", result.size(), result);
        return result;
    }

    // ====== 诊断合并 ======

    private void enrichDiagnostics(AnalyzerDiagnostics diag, ModuleContext ctx) {
        if (diag == null) return;
        diag.setClasspathAvailable(ctx.cpResult().isAvailable());
        diag.setJarCount(ctx.cpResult().getJars().size());
        diag.setClasspathSource(ctx.cpResult().getSource());
        diag.setClasspathWarnings(ctx.cpResult().getWarnings());
        diag.setClasspathErrors(ctx.cpResult().getErrors());
        diag.setClasspathCommand(ctx.cpResult().getCommand());
        diag.setClasspathExitCode(ctx.cpResult().getExitCode());
        diag.setClasspathDurationMs(ctx.cpResult().getDurationMs());
        diag.setClasspathStdoutTail(ctx.cpResult().getStdoutTail());
        diag.setClasspathStderrTail(ctx.cpResult().getStderrTail());
        diag.setClasspathTimedOut(ctx.cpResult().isTimedOut());

        if (ctx.index() != null) {
            diag.setRootPom(ctx.index().getRootPom() != null
                    ? ctx.index().getRootPom().toString() : null);
            diag.setModuleCount(ctx.index().getModuleCount());
            diag.setSourceRootCount(ctx.index().getAllSourceRoots().size());
            diag.setModules(ctx.index().getModules().stream()
                    .map(MavenModule::getDisplayName).toList());
            diag.setApplicationModuleCount(ctx.index().getApplicationModuleCount());
            diag.setBusinessModuleCount(ctx.index().getBusinessModuleCount());
            diag.setLibraryModuleCount(ctx.index().getLibraryModuleCount());
            diag.setBomModuleCount(ctx.index().getBomModuleCount());
            diag.setModuleTypes(ctx.index().getModules().stream()
                    .filter(m -> !m.isAggregator())
                    .collect(Collectors.toMap(
                            MavenModule::getDisplayName,
                            m -> m.getModuleType().name())));
        }
        if (ctx.targetModules() != null) {
            diag.setClasspathTargetModules(ctx.targetModules());
        }
    }

    // ====== 辅助方法 ======

    private void logSummary(AnalysisScope scope, AnalysisResult result) {
        AnalyzerDiagnostics diagnostics = result.diagnostics();
        log.info("白盒分析完成: scope={} endpoints={} callgraph_nodes={} findings={} flows={} clusters={}",
                scope.wireValue(), result.endpoints().size(), result.callGraph().size(),
                result.findings().size(), result.executionFlows().size(), result.clusters().size());
        if (diagnostics != null) {
            log.info("解析诊断: files={}/{} calls={} H={} M={} U={} cp={} jars={}",
                    diagnostics.getParsedFileCount(), diagnostics.getTotalSourceFiles(),
                    diagnostics.getTotalCalls(), diagnostics.getResolvedHigh(),
                    diagnostics.getResolvedMedium(), diagnostics.getUnresolved(),
                    diagnostics.getClasspathSource(), diagnostics.getJarCount());
        }
        if (diagnostics != null && diagnostics.getPassFailures() != null
                && !diagnostics.getPassFailures().isEmpty()) {
            log.warn("分析降级: {}", diagnostics.getPassFailures());
        }
    }
}
