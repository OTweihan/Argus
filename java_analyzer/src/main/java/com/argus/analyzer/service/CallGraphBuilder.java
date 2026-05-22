package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallGraphNode;
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

    public Map<String, CallGraphNode> build(Path sourcePath) {
        Map<String, CallGraphNode> graph = new LinkedHashMap<>();

        for (var entry : sourceFileScanner.scan(sourcePath)) {
            Path javaFile = entry.getKey();
            CompilationUnit cu = entry.getValue();

            for (ClassOrInterfaceDeclaration clazz : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                String className = clazz.getFullyQualifiedName()
                        .orElse(javaFile.getFileName().toString().replace(".java", ""));

                for (MethodDeclaration method : clazz.getMethods()) {
                    String nodeKey = className + "#" + method.getNameAsString();
                    String signature = method.getType().toString() + " " + method.getNameAsString()
                            + "(" + String.join(", ", method.getParameters().stream()
                            .map(p -> p.getType().toString())
                            .toList()) + ")";

                    List<String> callees = new ArrayList<>();
                    for (MethodCallExpr call : method.findAll(MethodCallExpr.class)) {
                        try {
                            ResolvedMethodDeclaration resolved = call.resolve();
                            String packageName = resolved.getPackageName();
                            String qualifiedClassName = packageName.isEmpty()
                                    ? resolved.getClassName()
                                    : packageName + "." + resolved.getClassName();
                            String calleeKey = qualifiedClassName + "#" + resolved.getName();
                            callees.add(calleeKey);
                        } catch (Exception e) {
                            // 回退：尝试解析 scope 类型（如 service.findById → 解析 service 的类型）
                            String fallback = resolveScopeType(call);
                            callees.add(fallback != null ? fallback + "#" + call.getNameAsString() : call.getNameAsString());
                        }
                    }

                    graph.put(nodeKey, new CallGraphNode(
                            className, method.getNameAsString(), signature, callees
                    ));
                }
            }
        }

        return graph;
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
            // 去掉泛型信息（如 List<Foo> → List）
            int genericStart = typeName.indexOf('<');
            if (genericStart > 0) typeName = typeName.substring(0, genericStart);
            return typeName;
        } catch (Exception ignored) {
            return null;
        }
    }
}
