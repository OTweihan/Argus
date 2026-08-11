package com.argus.analyzer.domain;

/**
 * AnalysisPass 执行失败信号（O-11）。
 *
 * <p>包装 pass 抛出的运行时异常并保留根因。由编排层用于必需 pass 失败时的
 * 作业失败传播。</p>
 */
public class AnalysisPassException extends RuntimeException {

    public AnalysisPassException(String passId, Throwable cause) {
        super("Analysis pass '" + passId + "' failed: " + cause.getMessage(), cause);
    }
}
