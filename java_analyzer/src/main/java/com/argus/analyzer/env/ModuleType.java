package com.argus.analyzer.env;

/**
 * Maven 模块类型分类。
 */
public enum ModuleType {

    /** 聚合父 POM（packaging=pom，无源码目录） */
    AGGREGATOR,
    /** BOM 依赖管理模块（packaging=pom，artifactId 含 bom） */
    BOM,
    /** 含 @SpringBootApplication 入口的应用模块 */
    APPLICATION,
    /** 含 Controller/Service 但无启动类的业务模块 */
    BUSINESS,
    /** 通用/基础设施模块（common/core/starter 等，不作为目标分析） */
    LIBRARY,
    /** 未能分类的模块 */
    UNKNOWN;

    /** 是否应作为目标分析模块。 */
    public boolean isTarget() {
        return this == APPLICATION || this == BUSINESS;
    }

    /** 是否为聚合类模块（不参与源码分析）。 */
    public boolean isAggregating() {
        return this == AGGREGATOR || this == BOM;
    }
}
