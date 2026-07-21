package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.*;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.*;

@Service
public class CallGraphBuilder {

    private static final Logger log = LoggerFactory.getLogger(CallGraphBuilder.class);

    private final SourceFileScanner sourceFileScanner;

    public CallGraphBuilder(SourceFileScanner sourceFileScanner) {
        this.sourceFileScanner = sourceFileScanner;
    }

    /**
     * 构建调用图，返回图结构和 diagnostics。
     */
    public BuildResult build(Path sourcePath) {
        return build(sourcePath, List.of());
    }

    public BuildResult build(Path sourcePath, List<Path> classpathJars) {
        var scanResult = sourceFileScanner.scan(sourcePath, null, classpathJars);
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();

        int totalCalls = 0;
        int resolvedHigh = 0;
        int resolvedMedium = 0;
        int unresolved = 0;

        for (var entry : scanResult.parsedFiles()) {
            Path javaFile = entry.getKey();
            CompilationUnit cu = entry.getValue();
            String sourceRelative = SourceFileScanner.relativize(sourcePath, javaFile);

            for (ClassOrInterfaceDeclaration clazz : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                String className = clazz.getFullyQualifiedName()
                        .orElse(javaFile.getFileName().toString().replace(".java", ""));

                for (MethodDeclaration method : clazz.getMethods()) {
                    String nodeKey = className + "#" + method.getNameAsString();
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
