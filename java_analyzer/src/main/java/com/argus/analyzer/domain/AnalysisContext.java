package com.argus.analyzer.domain;

import java.nio.file.Path;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;

/**
 * 一次分析的请求态上下文（O-11）。
 *
 * <p>持有每次分析的输入（源码路径、命令、classpath、进度/取消通道）与 pass
 * 产出积累。Pass 必须无状态：请求状态只存在于本 context / 局部变量。</p>
 */
public final class AnalysisContext {

    private final Path sourcePath;
    private final AnalysisCommand command;
    private final List<Path> classpathJars;
    private final AnalysisProgressListener progress;
    private final Map<Capability, Object> results = new LinkedHashMap<>();

    // 一次分析内的惰性资源槽位：供无依赖 pass 复用同一份规范化快照（如已解析
    // 源码索引）。请求态限定，非跨请求缓存；computeIfAbsent 保证并发下只求值一次。
    private final Map<String, Object> resources = new ConcurrentHashMap<>();

    public AnalysisContext(Path sourcePath, AnalysisCommand command,
                           List<Path> classpathJars, AnalysisProgressListener progress) {
        this.sourcePath = Objects.requireNonNull(sourcePath, "sourcePath");
        this.command = Objects.requireNonNull(command, "command");
        this.classpathJars = classpathJars == null ? List.of() : List.copyOf(classpathJars);
        this.progress = progress == null ? AnalysisProgressListener.NOOP : progress;
    }

    /** 已校验的源码 real path。 */
    public Path sourcePath() {
        return sourcePath;
    }

    public AnalysisCommand command() {
        return command;
    }

    /** 本次分析可用的 classpath JAR 列表（可能为空）。 */
    public List<Path> classpathJars() {
        return classpathJars;
    }

    public AnalysisProgressListener progress() {
        return progress;
    }

    /** 读取某能力对应的 pass 产出；未产出时为 {@code null}。 */
    @SuppressWarnings("unchecked")
    public <T> T get(Capability capability) {
        return (T) results.get(capability);
    }

    /** 记录 pass 产出（编排层在 pass 完成后调用）。 */
    public void put(Capability capability, Object value) {
        if (value != null) {
            results.put(capability, value);
        }
    }

    public Set<Capability> producedCapabilities() {
        return Collections.unmodifiableSet(new LinkedHashSet<>(results.keySet()));
    }

    /**
     * 一次分析内的惰性资源：以 {@code key} 只求值一次并复用（并发安全）。
     *
     * <p>供「一次分析只构建一次源码索引并供 pass 复用」使用，避免多个无依赖 pass
     * 各自重复扫描/解析。资源生命周期与本次 context 绑定，不进入任何跨请求缓存。</p>
     */
    @SuppressWarnings("unchecked")
    public <T> T computeIfAbsent(String key, Supplier<T> supplier) {
        Objects.requireNonNull(supplier, "supplier");
        return (T) resources.computeIfAbsent(key, k -> supplier.get());
    }
}
