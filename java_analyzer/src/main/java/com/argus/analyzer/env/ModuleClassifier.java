package com.argus.analyzer.env;

import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.JobCancelledException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * Maven 模块分类器。
 *
 * <p>为每个模块确定 moduleType，并按类型筛选目标分析模块。
 */
@Component
public class ModuleClassifier {

    private static final Logger log = LoggerFactory.getLogger(ModuleClassifier.class);

    /**
     * classifyAll 扫描完成后的信号缓存，避免 scoreModule 重复 scanSignals()。
     *
     * <p>按线程隔离（ThreadLocal）：{@link ModuleClassifier} 是 Spring 单例，而分析
     * 作业执行器默认 2 线程并发运行，多个作业会同时调用 classifyAll/selectTargets。
     * 若用共享 Map，A 作业的 clear()/put() 会与 B 作业的 getOrDefault() 竞争（破坏
     * HashMap 或丢失信号），且 A 的 clear 会清掉 B 的缓存迫使 B 全量重扫。
     * classifyAll → selectTargets 在同一作业线程内顺序执行，ThreadLocal 恰好
     * 覆盖该生命周期。</p>
     */
    private final ThreadLocal<Map<MavenModule, Signals>> _signalsCache = new ThreadLocal<>();

    // Library 关键词：artifactId 匹配其中之一则判定为基础设施/公共模块
    private static final Pattern LIBRARY_KEYWORDS = Pattern.compile(
            "^(.*[-.])?(common|core|shared|starter|framework|utils?|base|infra|support|sdk|client)([-.].*)?$",
            Pattern.CASE_INSENSITIVE
    );

    // Application 关键词：artifactId 匹配则加分
    private static final Pattern APPLICATION_KEYWORDS = Pattern.compile(
            "^(.*[-.])?(admin|server|web|boot|application|biz)([-.].*)?$",
            Pattern.CASE_INSENSITIVE
    );

    /**
     * 对索引中所有模块执行分类。
     * 已标记 AGGREGATOR 的模块跳过扫描。
     */
    public void classifyAll(MavenModuleIndex index) {
        classifyAll(index, AnalysisProgressListener.NOOP);
    }

    /**
     * 对索引中所有模块执行分类，支持协作取消（O-04）：逐模块/逐文件的安全边界
     * 检查 {@code progress.isCancelled()}，取消时抛 {@link JobCancelledException}。
     */
    public void classifyAll(MavenModuleIndex index, AnalysisProgressListener progress) {
        _signalsCache.set(new HashMap<>());
        try {
            for (MavenModule module : index.getModules()) {
                if (progress.isCancelled()) {
                    throw new JobCancelledException("Module classification cancelled");
                }
                if (module.getModuleType() == ModuleType.AGGREGATOR) {
                    // 扫描阶段已标记，检查是否应转为 BOM
                    if (isBomModule(module)) {
                        module.setModuleType(ModuleType.BOM);
                    }
                    continue;
                }
                // 先 scanSignals，结果缓存供后续 scoreModule() 复用
                Signals signals = scanSignals(module, progress);
                _signalsCache.get().put(module, signals);
                ModuleType type = classifySingle(module, signals);
                module.setModuleType(type);
                log.debug("[CLASSIFIER] Module {}: classified as {}", module.getDisplayName(), type);
            }

            log.info("[CLASSIFIER] Classification complete: apps={} biz={} lib={} agg={} bom={}",
                    countByType(index, ModuleType.APPLICATION),
                    countByType(index, ModuleType.BUSINESS),
                    countByType(index, ModuleType.LIBRARY),
                    countByType(index, ModuleType.AGGREGATOR),
                    countByType(index, ModuleType.BOM));
        } finally {
            // ThreadLocal 信号缓存必须显式清理：作业线程池跨作业复用，若不 remove，
            // 最后一个作业的 Map<MavenModule, Signals> 会一直挂在线程上（含模块对象
            // 引用），且下一作业 set 前短暂可见旧数据。classifyAll 结束即失效。
            _signalsCache.remove();
        }
    }

    /**
     * 返回应作为目标分析模块的列表（APPLICATION + BUSINESS）。
     * 必须先调用 {@link #classifyAll(MavenModuleIndex)}。
     */
    public List<MavenModule> selectTargets(MavenModuleIndex index) {
        return selectTargets(index, AnalysisProgressListener.NOOP);
    }

    /**
     * 返回应作为目标分析模块的列表，支持协作取消（O-04）：评分阶段读取源文件时
     * 检查 {@code progress.isCancelled()}。
     */
    public List<MavenModule> selectTargets(MavenModuleIndex index, AnalysisProgressListener progress) {
        List<MavenModule> targets = index.getModules().stream()
                .filter(m -> m.getModuleType() != null && m.getModuleType().isTarget())
                .sorted(Comparator.<MavenModule, Integer>comparing(
                                m -> m.getModuleType() == ModuleType.APPLICATION ? 0 : 1)
                        .thenComparingInt(m -> -scoreModule(m, progress)))
                .toList();

        if (targets.isEmpty()) {
            log.warn("[CLASSIFIER] No target modules found after classification");
        } else {
            log.info("[CLASSIFIER] Target modules ({}): {}", targets.size(),
                    targets.stream().map(m -> m.getDisplayName() + "[" + m.getModuleType() + "]").toList());
        }
        return targets;
    }

    // ====== 单模块分类 ======

    ModuleType classifySingle(MavenModule module, Signals signals) {
        if (module.isPomPackaging() && module.getSourceRoots().isEmpty()) {
            return isBomModule(module) ? ModuleType.BOM : ModuleType.AGGREGATOR;
        }
        boolean hasSpringBootApp = signals.hasSpringBootApplication();
        boolean hasMainClass = signals.hasMainClass();
        int bizScore = signals.businessScore();

        boolean isLib = isLibraryModule(module, signals);

        if (hasSpringBootApp && hasMainClass) {
            return ModuleType.APPLICATION;
        }

        if (isLib && signals.controllerCount() == 0) {
            return ModuleType.LIBRARY;
        }

        if (bizScore >= 3 || hasSpringBootApp) {
            return ModuleType.BUSINESS;
        }

        // 含少量 Controller 但 artifactId 像 library → 仍归为 BUSINESS
        if (signals.controllerCount() > 0) {
            return ModuleType.BUSINESS;
        }

        return ModuleType.LIBRARY;
    }

    // ====== 库模块判定 ======

    boolean isLibraryModule(MavenModule module, Signals signals) {
        if (signals.hasSpringBootApplication()) {
            return false;
        }
        if (!LIBRARY_KEYWORDS.matcher(module.getArtifactId()).matches()) {
            return false;
        }
        // 即使 artifactId 匹配关键词，有 Controller 且数量多时不归为 LIBRARY
        return signals.controllerCount() == 0;
    }

    boolean isBomModule(MavenModule module) {
        String aid = module.getArtifactId();
        return aid != null && aid.toLowerCase().contains("bom");
    }

    // ====== 信号扫描 ======

    Signals scanSignals(MavenModule module, AnalysisProgressListener progress) {
        Signals signals = new Signals();
        for (Path srcDir : module.getSourceRoots()) {
            if (!Files.isDirectory(srcDir)) continue;
            try (Stream<Path> files = Files.walk(srcDir)) {
                List<Path> javaFiles = files
                        .filter(p -> p.toString().endsWith(".java"))
                        .toList();

                for (Path javaFile : javaFiles) {
                    if (progress.isCancelled()) {
                        throw new JobCancelledException("Module signal scan cancelled");
                    }
                    try {
                        String content = Files.readString(javaFile);

                        if (content.contains("@SpringBootApplication")
                                || content.contains("@SpringBootConfiguration")) {
                            signals.springBootApp = true;
                        }
                        if (content.contains("@RestController")) {
                            signals.controllerCount++;
                        } else if (content.contains("@Controller")) {
                            signals.controllerCount++;
                        }
                        if (content.contains("@Service")) {
                            signals.serviceCount++;
                        }
                        if (content.contains("@Repository")) {
                            signals.repositoryCount++;
                        }
                        // Mapper 通常是 MyBatis 等框架的注解
                        if (content.contains("@Mapper")) {
                            signals.mapperCount++;
                        }
                        if (content.contains("@Entity") || content.contains("@Table(name =")) {
                            signals.entityCount++;
                        }
                        // 检查 main 方法
                        if (!signals.hasMain && content.contains("public static void main")) {
                            signals.hasMain = true;
                        }
                    } catch (IOException ex) {
                        log.debug("[CLASSIFIER] Failed to read {}: {}", javaFile, ex.toString());
                    }
                }
            } catch (IOException ex) {
                log.debug("[CLASSIFIER] Failed to walk source dir {}: {}", srcDir, ex.toString());
            }
        }
        return signals;
    }

    // ====== 评分（用于排序） ======

    int scoreModule(MavenModule module, AnalysisProgressListener progress) {
        if (module.getModuleType() == ModuleType.APPLICATION) {
            return 50; // 应用模块默认高分
        }
        if (module.getModuleType() == ModuleType.BUSINESS) {
            // 优先复用 classifyAll 阶段写入的线程本地扫描缓存，避免重复 I/O。
            // classifyAll 必然先于 selectTargets 在同线程执行，因此缓存非空；
            // get() 为 null 仅发生在绕过 classifyAll 直接调用的防御路径。
            Map<MavenModule, Signals> cache = _signalsCache.get();
            Signals s = cache != null
                    ? cache.getOrDefault(module, scanSignals(module, progress))
                    : scanSignals(module, progress);
            return s.businessScore();
        }
        return 0;
    }

    // ====== 辅助 ======

    private int countByType(MavenModuleIndex index, ModuleType type) {
        return (int) index.getModules().stream()
                .filter(m -> m.getModuleType() == type)
                .count();
    }

    // ====== 内部信号类 ======

    static class Signals {
        boolean springBootApp;
        boolean hasMain;
        int controllerCount;
        int serviceCount;
        int repositoryCount;
        int mapperCount;
        int entityCount;

        boolean hasSpringBootApplication() {
            return springBootApp;
        }

        boolean hasMainClass() {
            return hasMain;
        }

        int controllerCount() {
            return controllerCount;
        }

        int businessScore() {
            return controllerCount * 3
                    + serviceCount * 2
                    + repositoryCount * 2
                    + mapperCount * 2
                    + entityCount * 1;
        }
    }
}
