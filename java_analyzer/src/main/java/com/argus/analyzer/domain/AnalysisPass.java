package com.argus.analyzer.domain;

import java.util.Set;

/**
 * 分析 pass SPI（O-11）。
 *
 * <p>SPI 不暴露 Spring / HTTP DTO 类型。Pass 默认按单例使用，必须无状态且
 * 线程安全：请求状态只存在于 {@link AnalysisContext} 与局部变量，不得修改共享
 * AST、其他 pass 结果或最终 HTTP DTO。</p>
 *
 * <p>实现约定：协作取消（{@link JobCancelledException}）必须原样传播，不得
 * 降级吞掉；可选 pass 抛出的其他运行时异常由编排层显式降级进 diagnostics。</p>
 */
public interface AnalysisPass {

    /** 稳定 ID（诊断/日志/降级记录使用）。 */
    String id();

    /** 本 pass 产出的能力（同一能力最多由一个 pass 产出）。 */
    Capability produced();

    /** 本 pass 消费的能力；集合中每项必须由某个已注册 pass 产出。 */
    Set<Capability> requires();

    /** 失败语义：必需 pass 失败使作业失败；可选 pass 失败进入 diagnostics 降级。 */
    boolean required();

    /** 在给定上下文上执行，返回不可变 contribution。 */
    AnalysisContribution run(AnalysisContext context);
}
