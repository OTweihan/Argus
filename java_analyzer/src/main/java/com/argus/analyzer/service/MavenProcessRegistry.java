package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.support.ProcessTreeKiller;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Maven 外部进程注册表（O-04）。
 *
 * <p>按 {@link AnalysisProgressListener} 实例登记作业期间 spawn 的 Maven
 * {@link Process}，取消/超时/deadline 时按 key 销毁整个进程树（含后代）。
 * 以 progress 实例为 key：MavenExecutor 不感知 jobId；非作业同步路径使用
 * 共享的 {@link AnalysisProgressListener#NOOP}，其 key 不登记，避免跨作业
 * 误杀。进程正常退出时经 {@code onExit()} 自移除。
 */
@Component
public class MavenProcessRegistry {

    private final Map<AnalysisProgressListener, Set<Process>> registry = new ConcurrentHashMap<>();

    /**
     * 登记进程。NOOP（非作业路径）不登记。
     */
    public void register(AnalysisProgressListener key, Process process) {
        if (key == null || key == AnalysisProgressListener.NOOP) {
            return;
        }
        registry.computeIfAbsent(key, k -> ConcurrentHashMap.newKeySet()).add(process);
        process.onExit().thenRun(() -> {
            Set<Process> procs = registry.get(key);
            if (procs != null) {
                procs.remove(process);
            }
        });
    }

    /**
     * 销毁该 key 名下所有存活进程树并清理登记。
     */
    public void destroyFor(AnalysisProgressListener key) {
        if (key == null || key == AnalysisProgressListener.NOOP) {
            return;
        }
        Set<Process> procs = registry.remove(key);
        if (procs == null || procs.isEmpty()) {
            return;
        }
        for (Process process : procs) {
            ProcessTreeKiller.kill(process);
        }
    }
}
