package com.argus.analyzer.env;

/**
 * Classpath 解析策略模式。
 */
public enum ClasspathMode {

    /** 仅从缓存读取，不执行 Maven */
    CACHE_ONLY,
    /** 运行 Maven 生成 classpath */
    MAVEN,
    /** 智能模式：缓存 → online → offline → source-only 降级 */
    AUTO,
    /** 跳过 classpath 生成，仅源码分析 */
    SOURCE_ONLY;

    public boolean allowsMavenExecution() {
        return this == MAVEN || this == AUTO;
    }
}
