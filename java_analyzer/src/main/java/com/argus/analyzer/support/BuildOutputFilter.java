package com.argus.analyzer.support;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 「什么构成分析输入」的目录排除规则（扫描与指纹共用的单一事实源）。
 *
 * <p>两类排除收口于此：</p>
 * <ul>
 *   <li>构建输出（{@code target/**}、{@code build/}、{@code out/}）：此前分散在
 *       两处且口径不一——{@code SourceFileScanner} 排除了它们，
 *       {@code SourceFingerprint} 则没有，导致缓存键随构建状态漂移。</li>
 *   <li>测试源码（{@code src/test/**}，Maven/Gradle 约定布局）：测试代码从不
 *       是生产端点/缺陷的分析对象——测试 fixture 里的 {@code @RestController}
 *       会成为假端点并污染调用图；classpath 解析用的是 {@code includeScope=compile}，
 *       测试依赖本就不可解析。默认排除可同时消除误报并减少约 30-60% 解析量。
 *       扫描与指纹必须同口径应用，避免缓存键与实际分析输入脱节。</li>
 * </ul>
 *
 * <p>新增排除规则时只改本类。</p>
 */
public final class BuildOutputFilter {

    /** 构建产物目录名（按路径段精确匹配，不做子串匹配）。 */
    private static final Set<String> BUILD_OUTPUT_SEGMENTS = Set.of("target", "build", "out");

    /** 测试源码根的路径段约定：任意层级的 {@code src/test/**}。 */
    private static final String SRC_SEGMENT = "src";
    private static final String TEST_SEGMENT = "test";

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

    /** 路径是否位于任一测试源码根（{@code src/test/**}）之下。 */
    public static boolean isTestSource(Path path) {
        List<String> segments = new ArrayList<>();
        for (Path segment : path) {
            segments.add(segment.toString());
        }
        for (int i = 0; i + 1 < segments.size(); i++) {
            if (SRC_SEGMENT.equals(segments.get(i)) && TEST_SEGMENT.equals(segments.get(i + 1))) {
                return true;
            }
        }
        return false;
    }

    /**
     * 路径是否被排除出分析输入（扫描过滤与指纹输入共用同一判定，
     * 保证缓存键身份与实际解析集合一致）。
     */
    public static boolean isExcludedFromAnalysis(Path path) {
        return isUnder(path) || isTestSource(path);
    }
}
