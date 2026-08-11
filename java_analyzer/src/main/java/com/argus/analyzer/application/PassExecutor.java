package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisPassException;
import com.argus.analyzer.domain.AnalysisResult;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Executor;

/**
 * AnalysisPass 编排执行器（O-11）。
 *
 * <p>按能力依赖拓扑展开计划：每一轮挑选所有依赖已满足（requires 均已产出）的
 * pass 并行执行，直到全部完成。结果顺序按计划固定，可重复。无依赖 pass 并行、
 * 有依赖 pass 串行（分波）。</p>
 *
 * <p>失败语义：必需 pass 失败使整体失败并向上传播；可选 pass 失败显式降级——
 * 记录到 {@code AnalyzerDiagnostics.passFailures}、经 progress 发 WARN 事件并
 * 打日志，不静默吞错。{@link JobCancelledException} 恒原样传播，绝不降级。</p>
 */
public final class PassExecutor {

    private static final Logger log = LoggerFactory.getLogger(PassExecutor.class);

    private final Executor executor;

    public PassExecutor(Executor executor) {
        this.executor = Objects.requireNonNull(executor, "executor");
    }

    public AnalysisResult execute(List<AnalysisPass> passes, AnalysisContext context) {
        if (passes == null || passes.isEmpty()) {
            AnalyzerDiagnostics diagnostics = new AnalyzerDiagnostics();
            diagnostics.setPassFailures(List.of());
            return new AnalysisResult(List.of(), Map.of(), List.of(), List.of(), List.of(), diagnostics);
        }

        Set<Capability> available = new LinkedHashSet<>(context.producedCapabilities());
        List<AnalysisPass> pending = new ArrayList<>(passes);
        AnalyzerDiagnostics diagnostics = new AnalyzerDiagnostics();
        List<String> passFailures = new ArrayList<>();

        while (!pending.isEmpty()) {
            List<AnalysisPass> ready = new ArrayList<>();
            for (AnalysisPass pass : pending) {
                if (available.containsAll(pass.requires())) {
                    ready.add(pass);
                }
            }
            if (ready.isEmpty()) {
                // 计划内 pass 都无法就绪：PlanValidator 已保证声明依赖无环，此分支只可能是
                // 可选 pass 失败导致其产出能力缺失、而下游 pass 又依赖该能力。
                List<String> missing = pending.stream()
                        .filter(pass -> !available.containsAll(pass.requires()))
                        .flatMap(pass -> pass.requires().stream())
                        .filter(required -> !available.contains(required))
                        .distinct()
                        .map(Capability::name)
                        .toList();
                throw new IllegalStateException(
                        "Unsatisfiable pass dependencies (optional pass degradation removed "
                                + "capabilities " + missing + " required by "
                                + pending.stream().map(AnalysisPass::id).toList() + ")");
            }
            pending.removeAll(ready);

            List<CompletableFuture<AnalysisContribution>> futures = new ArrayList<>();
            try {
                for (AnalysisPass pass : ready) {
                    futures.add(CompletableFuture.supplyAsync(
                            () -> Objects.requireNonNull(
                                    pass.run(context), "Pass '" + pass.id() + "' returned null"),
                            executor));
                }
            } catch (RuntimeException | Error submissionFailure) {
                // 部分任务已提交而后续提交被有界执行器拒绝时，必须等待已提交任务
                // 收敛，避免作业先失败、调用方释放源码快照后后台任务仍继续读取。
                awaitSettlement(futures);
                throw submissionFailure;
            }
            // 同波任务全部结束后再处理各自结果。这样任一必需 pass 失败/取消时，
            // 不会遗留仍访问源码快照的后台分析任务。
            awaitSettlement(futures);
            for (int i = 0; i < ready.size(); i++) {
                AnalysisPass pass = ready.get(i);
                try {
                    AnalysisContribution contribution = futures.get(i).join();
                    // 产出按 pass 声明的能力记录（而非 contribution 声称的能力），
                    // 避免 pass 返回不一致贡献时污染 context / 能力集。
                    context.put(pass.produced(), contribution.value());
                    available.add(pass.produced());
                    if (contribution.diagnostics() != null) {
                        diagnostics = mergeDiagnostics(diagnostics, contribution.diagnostics());
                    }
                } catch (CompletionException error) {
                    Throwable cause = unwrap(error);
                    if (cause instanceof JobCancelledException cancelled) {
                        throw cancelled;
                    }
                    if (cause instanceof Error fatal) {
                        throw fatal;
                    }
                    if (pass.required()) {
                        throw cause instanceof RuntimeException runtime
                                ? runtime
                                : new AnalysisPassException(pass.id(), cause);
                    }
                    passFailures.add(pass.id() + ": " + rootMessage(cause));
                    context.progress().onEvent("analysis", "WARN",
                            "Pass '" + pass.id() + "' failed; result degraded: " + rootMessage(cause));
                    log.warn("Optional pass '{}' failed; result degraded: {}", pass.id(),
                            rootMessage(cause), cause);
                }
            }
        }

        diagnostics.setPassFailures(passFailures.isEmpty() ? List.of() : List.copyOf(passFailures));
        return new AnalysisResult(
                listOrEmpty(context.get(Capability.ENDPOINTS)),
                mapOrEmpty(context.get(Capability.CALL_GRAPH)),
                listOrEmpty(context.get(Capability.FINDINGS)),
                listOrEmpty(context.get(Capability.FLOWS)),
                listOrEmpty(context.get(Capability.CLUSTERS)),
                diagnostics);
    }

    /** 等待已提交 Future 全部进入终态，同时延迟到逐项处理时再传播具体失败。 */
    private static void awaitSettlement(List<? extends CompletableFuture<?>> futures) {
        if (futures.isEmpty()) {
            return;
        }
        CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new))
                .handle((ignored, error) -> null)
                .join();
    }

    /** 合并 pass 附加诊断（目前仅 call graph pass 提供解析统计）。 */
    private static AnalyzerDiagnostics mergeDiagnostics(AnalyzerDiagnostics target,
                                                        AnalyzerDiagnostics source) {
        if (source == null) {
            return target;
        }
        if (target == null) {
            return source;
        }
        target.setTotalSourceFiles(source.getTotalSourceFiles());
        target.setParsedFileCount(source.getParsedFileCount());
        target.setFailedFileCount(source.getFailedFileCount());
        target.setFailedFiles(source.getFailedFiles());
        target.setTotalCalls(source.getTotalCalls());
        target.setResolvedHigh(source.getResolvedHigh());
        target.setResolvedMedium(source.getResolvedMedium());
        target.setResolvedLow(source.getResolvedLow());
        target.setUnresolved(source.getUnresolved());
        return target;
    }

    private static Throwable unwrap(Throwable throwable) {
        Throwable current = throwable;
        while (current instanceof CompletionException) {
            current = current.getCause();
        }
        return current;
    }

    private static String rootMessage(Throwable throwable) {
        Throwable current = throwable;
        while (current.getCause() != null) {
            current = current.getCause();
        }
        String message = current.getMessage();
        return message == null ? current.getClass().getSimpleName() : message;
    }

    @SuppressWarnings("unchecked")
    private static <T> List<T> listOrEmpty(Object value) {
        return value == null ? List.of() : (List<T>) value;
    }

    @SuppressWarnings("unchecked")
    private static <K, V> Map<K, V> mapOrEmpty(Object value) {
        return value == null ? Map.of() : (Map<K, V>) value;
    }
}
