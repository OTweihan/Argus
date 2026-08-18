package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.AnalyzerDiagnostics;
import com.argus.analyzer.domain.model.CallEdge;
import com.argus.analyzer.domain.model.CallGraphNode;
import com.argus.analyzer.domain.model.Confidence;
import com.argus.analyzer.domain.model.MethodKey;
import com.argus.analyzer.domain.model.ResolutionType;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Path;
import java.util.*;

/**
 * 调用图构建（O-11 起实现 {@link AnalysisPass}，无状态、线程安全）。
 */
public class CallGraphBuilder implements AnalysisPass {

    private static final Logger log = LoggerFactory.getLogger(CallGraphBuilder.class);

    private final SourceFileScanner sourceFileScanner;

    public CallGraphBuilder(SourceFileScanner sourceFileScanner) {
        this.sourceFileScanner = sourceFileScanner;
    }

    @Override
    public String id() {
        return "callgraph";
    }

    @Override
    public Capability produced() {
        return Capability.CALL_GRAPH;
    }

    @Override
    public Set<Capability> requires() {
        return Set.of();
    }

    @Override
    public boolean required() {
        return true;
    }

    @Override
    public AnalysisContribution run(AnalysisContext context) {
        return guarded(context, () -> {
            BuildResult result = buildFrom(sourceFileScanner.scanForContext(context),
                    context.sourcePath(), context.progress());
            return new AnalysisContribution(Capability.CALL_GRAPH, result.graph(), result.diagnostics());
        });
    }

    /**
     * 构建调用图，返回图结构和 diagnostics。
     */
    public BuildResult build(Path sourcePath) {
        return build(sourcePath, List.of());
    }

    public BuildResult build(Path sourcePath, List<Path> classpathJars) {
        return build(sourcePath, classpathJars, AnalysisProgressListener.NOOP);
    }

    /**
     * 构建调用图，支持协作取消（O-04）：扫描与逐文件处理的安全边界检查
     * {@code progress.isCancelled()}，取消时抛 {@link JobCancelledException}。
     */
    public BuildResult build(Path sourcePath, List<Path> classpathJars, AnalysisProgressListener progress) {
        return buildFrom(sourceFileScanner.scan(sourcePath, null, classpathJars, progress),
                sourcePath, progress);
    }

    private BuildResult buildFrom(SourceFileScanner.ScanResult scanResult,
                                  Path sourcePath, AnalysisProgressListener progress) {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();
        // 每个「类#方法」名字键的命中次数：用于检测重载，首个重载保留名字键（名字键
        // 是唯一稳定身份，供仅有方法名的消费方反查），后续重载改用签名键避免静默覆盖。
        Map<String, Integer> overloadCounts = new HashMap<>();

        int totalCalls = 0;
        int resolvedHigh = 0;
        int resolvedMedium = 0;
        int unresolved = 0;

        for (var entry : scanResult.parsedFiles()) {
            if (progress.isCancelled()) {
                throw new JobCancelledException("Call graph build cancelled");
            }
            Path javaFile = entry.getKey();
            CompilationUnit cu = entry.getValue();
            String sourceRelative = SourceFileScanner.relativize(sourcePath, javaFile);

            for (ClassOrInterfaceDeclaration clazz : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                String className = clazz.getFullyQualifiedName()
                        .orElse(javaFile.getFileName().toString().replace(".java", ""));

                for (MethodDeclaration method : clazz.getMethods()) {
                    String nameKey = MethodKey.nameKey(className, method.getNameAsString());
                    int seen = overloadCounts.merge(nameKey, 1, Integer::sum);
                    String nodeKey = seen == 1
                            ? nameKey
                            : MethodKey.signatureKey(className, method.getNameAsString(),
                                    method.getParameters().stream()
                                            .map(p -> p.getType().asString())
                                            .toList());
                    String signature = method.getType().toString() + " " + method.getNameAsString()
                            + "(" + String.join(", ", method.getParameters().stream()
                            .map(p -> p.getType().toString())
                            .toList()) + ")";

                    List<CallEdge> calleeDetails = new ArrayList<>();
                    for (MethodCallExpr call : method.findAll(MethodCallExpr.class)) {
                        int line = call.getBegin().map(b -> b.line).orElse(0);
                        CallEdge edge = resolve(call, sourceRelative, line);
                        calleeDetails.add(edge);

                        totalCalls++;
                        switch (edge.confidence()) {
                            case HIGH -> resolvedHigh++;
                            case MEDIUM -> resolvedMedium++;
                            case UNKNOWN -> unresolved++;
                        }
                    }

                    graph.put(nodeKey, new CallGraphNode(
                            className, method.getNameAsString(), signature, calleeDetails
                    ));
                }
            }
        }

        AnalyzerDiagnostics diagnostics = new AnalyzerDiagnostics(
                scanResult.totalFiles(),
                scanResult.parsedFiles().size(),
                scanResult.failures().size(),
                scanResult.failures(),
                totalCalls,
                resolvedHigh,
                resolvedMedium,
                0, // resolvedLow — resolve() 从不返回 LOW，保留字段用于 API 兼容
                unresolved
        );

        return new BuildResult(graph, diagnostics);
    }

    /**
     * 三层解析链：SymbolSolver → ScopeFallback → Unresolved
     *
     * <p>边的 {@code to} 统一使用名字键（{@code className#methodName}）：解析到重载方法时
     * 指向首个重载节点。签名级消歧不在边侧进行，因为 scope 回退与 unresolved 两层仅能拿到
     * 方法名、端点入口（{@code EndpointInfo}）同样只有方法名；统一名字键保证这些消费方的
     * 反查语义稳定。</p>
     */
    private CallEdge resolve(MethodCallExpr call, String sourceFile, int line) {
        // Layer 1: 精确解析
        try {
            ResolvedMethodDeclaration resolved = call.resolve();
            String packageName = resolved.getPackageName();
            String qualifiedClassName = packageName.isEmpty()
                    ? resolved.getClassName()
                    : packageName + "." + resolved.getClassName();
            String calleeKey = qualifiedClassName + "#" + resolved.getName();
            return new CallEdge(
                    calleeKey, resolved.getName(), qualifiedClassName,
                    ResolutionType.SYMBOL_SOLVER, Confidence.HIGH,
                    List.of(), sourceFile, line
            );
        } catch (RuntimeException ex) {
            log.debug("[RESOLVE] Symbol-solver fallback on {}:{} — {}", sourceFile, line, ex.toString());
        }

        // Layer 2: scope 类型回退
        String scopeType = resolveScopeType(call);
        if (scopeType != null) {
            String calleeKey = scopeType + "#" + call.getNameAsString();
            return new CallEdge(
                    calleeKey, call.getNameAsString(), scopeType,
                    ResolutionType.SOURCE_SCOPE_FALLBACK, Confidence.MEDIUM,
                    List.of(), sourceFile, line
            );
        }

        // Layer 3: 无法解析，保留原始信息
        String rawName = call.getNameAsString();
        return new CallEdge(
                rawName, rawName, "",
                ResolutionType.UNRESOLVED, Confidence.UNKNOWN,
                List.of(), sourceFile, line
        );
    }

    /**
     * 当 call.resolve() 失败时，尝试解析 scope 表达式的类型。
     * 例如 service.findById(id) 可解析出 service 的类型名。
     */
    private String resolveScopeType(MethodCallExpr call) {
        try {
            Optional<Expression> scope = call.getScope();
            if (scope.isEmpty()) return null;
            String typeName = scope.get().calculateResolvedType().describe();
            int genericStart = typeName.indexOf('<');
            if (genericStart > 0) typeName = typeName.substring(0, genericStart);
            return typeName;
        } catch (RuntimeException ex) {
            log.debug("[RESOLVE] Scope-type fallback failed — {}", ex.toString());
            return null;
        }
    }

    /**
     * 构建结果，包含调用图和 diagnostics。
     */
    public record BuildResult(
            Map<String, CallGraphNode> graph,
            AnalyzerDiagnostics diagnostics
    ) {}
}
