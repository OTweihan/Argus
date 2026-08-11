package com.argus.analyzer.domain;

import java.nio.file.Path;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

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
}
