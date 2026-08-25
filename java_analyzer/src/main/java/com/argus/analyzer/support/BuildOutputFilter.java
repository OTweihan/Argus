package com.argus.analyzer.support;

import java.nio.file.Path;
import java.util.Set;

/**
 * 构建输出目录判定（扫描与指纹共用的单一事实源）。
 *
 * <p>「什么构成分析输入」的目录排除规则此前分散在两处且口径不一：
 * {@code SourceFileScanner} 按段排除 {@code target/**}（Maven），
 * {@code SourceFingerprint} 则不排除任何目录——{@code target/generated-sources}
 * 的注解处理器产物参与指纹却从不参与扫描：既让同一源码树的缓存键随构建状态
 * 漂移，又浪费全量生成树的哈希 IO。Gradle 的 {@code build/} 与 IDE 的
 * {@code out/} 此前两层都不排除，属反向缺口。</p>
 *
 * <p>统一收口于此：扫描排除与指纹输入过滤必须调用本类，新增构建输出目录时
 * 只改这一处。</p>
 */
public final class BuildOutputFilter {

    /** 构建产物目录名（按路径段精确匹配，不做子串匹配）。 */
    private static final Set<String> BUILD_OUTPUT_SEGMENTS = Set.of("target", "build", "out");

    private BuildOutputFilter() {}

    /** 路径是否位于任一构建输出目录之下。 */
    public static boolean isUnder(Path path) {
        for (Path segment : path) {
            if (BUILD_OUTPUT_SEGMENTS.contains(segment.toString())) {
                return true;
            }
        }
        return false;
    }
}
