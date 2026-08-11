package com.argus.analyzer.domain;

/**
 * 分析进度与协作取消的统一通道（O-04）。
 *
 * <p>{@code onEvent} 负责进度事件；{@code isCancelled} 作为协作取消令牌，
 * 被扫描/分析/聚类/Maven 等在安全边界轮询。默认实现恒为 {@code false}，
 * 因此既有的 {@link #NOOP} lambda 与方法引用（如 {@code job::addEvent}）
 * 保持源兼容；非作业路径（同步 {@code /analyze}）自然不参与取消。
 */
public interface AnalysisProgressListener {

    AnalysisProgressListener NOOP = (stage, level, message) -> {};

    void onEvent(String stage, String level, String message);

    /** 协作取消信号：作业被请求取消时返回 true。默认不取消。 */
    default boolean isCancelled() {
        return false;
    }
}
