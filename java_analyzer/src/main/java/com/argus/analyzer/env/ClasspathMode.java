package com.argus.analyzer.env;

/**
 * Classpath 解析策略模式。
 *
 * <p>历史上有 {@code MAVEN} 模式，但 {@code ModuleClasspathResolver} 只对
 * {@code SOURCE_ONLY}/{@code CACHE_ONLY} 显式分支，{@code MAVEN} 与 {@code AUTO}
 * 走完全相同的「缓存→online→offline→source 降级」路径，且无任何配置绑定或
 * setter 调用方会把它置为 {@code MAVEN}（{@code classpathMode} 恒为默认
 * {@code AUTO}）。为消除「配置被静默忽略」的语义陷阱，已删除该常量。</p>
 */
public enum ClasspathMode {

    /** 仅从缓存读取，不执行 Maven */
    CACHE_ONLY,
    /** 智能模式：缓存 → online → offline → source-only 降级 */
    AUTO,
    /** 跳过 classpath 生成，仅源码分析 */
    SOURCE_ONLY;
}
