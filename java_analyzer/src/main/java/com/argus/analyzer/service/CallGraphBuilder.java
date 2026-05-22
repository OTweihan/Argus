package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
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
                            String calleeKey = resolved.getClassName() + "#" + resolved.getName();
                            callees.add(calleeKey);
                        } catch (Exception e) {
                            // Method resolution may fail for external libraries
                            callees.add(call.getNameAsString());
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
}
