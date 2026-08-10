package com.argus.analyzer.service;

/**
 * 分析作业被协作取消时抛出的专用信号（O-04）。
 *
 * <p>故意<b>不</b>继承 {@link com.argus.analyzer.env.ClasspathException}：
 * {@code MavenClasspathGateway} 的 {@code catch (ClasspathException)} 因此
 * 不会把取消降级为普通 classpath 失败并继续分析，而是让取消信号一路传播到
 * {@link AnalysisJobService#runJob}，落 CANCELLED 终态。
 */
public class JobCancelledException extends RuntimeException {

    public JobCancelledException() {
        super("Analysis job cancelled");
    }

    public JobCancelledException(String message) {
        super(message);
    }
}
