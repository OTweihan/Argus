package com.argus.analyzer.support;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 进程树强制终止工具 — {@code MavenExecutor} 与 {@code MavenProcessRegistry} 共用。
 *
 * <p>取消/超时/deadline 时销毁整个进程树（含后代）。两处此前各自手写一份近乎
 * 相同的 {@code killProcessTree}，收敛为单一实现。{@code ProcessHandle.descendants()}
 * 在部分平台不可用或抛 {@link SecurityException} 时降级为仅终止根进程。</p>
 */
public final class ProcessTreeKiller {

    private static final Logger log = LoggerFactory.getLogger(ProcessTreeKiller.class);

    private ProcessTreeKiller() {}

    public static void kill(Process process) {
        if (process == null || !process.isAlive()) {
            return;
        }
        try {
            process.descendants().forEach(ProcessHandle::destroyForcibly);
        } catch (UnsupportedOperationException | SecurityException e) {
            log.debug("ProcessHandle descendants unavailable: {}", e.getMessage());
        }
        process.destroyForcibly();
        log.warn("已强制终止 Maven 进程树: pid={}", process.pid());
    }
}
