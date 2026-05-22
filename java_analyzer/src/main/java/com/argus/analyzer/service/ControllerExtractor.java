package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.EndpointInfo;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.MemberValuePair;
import com.github.javaparser.ast.expr.NormalAnnotationExpr;
import com.github.javaparser.ast.expr.SingleMemberAnnotationExpr;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.*;
import java.util.stream.Collectors;

@Service
public class ControllerExtractor {

    private static final Logger log = LoggerFactory.getLogger(ControllerExtractor.class);

    private static final Set<String> REQUEST_MAPPING_ANNOTATIONS = Set.of(
            "RequestMapping", "GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping"
    );

    private final SourceFileScanner sourceFileScanner;

    public ControllerExtractor(SourceFileScanner sourceFileScanner) {
        this.sourceFileScanner = sourceFileScanner;
    }

    public List<EndpointInfo> extract(Path sourcePath) {
        List<EndpointInfo> endpoints = new ArrayList<>();

        for (var entry : sourceFileScanner.scan(sourcePath)) {
            Path javaFile = entry.getKey();
            CompilationUnit cu = entry.getValue();

            Optional<ClassOrInterfaceDeclaration> controllerClass = findControllerClass(cu);
            if (controllerClass.isEmpty()) {
                continue;
            }

            String classBasePath = extractClassBasePath(controllerClass.get());
            String className = controllerClass.get().getFullyQualifiedName()
                    .orElse(javaFile.getFileName().toString().replace(".java", ""));

            for (MethodDeclaration method : controllerClass.get().getMethods()) {
                AnnotationExpr mappingAnnotation = findMappingAnnotation(method);
                if (mappingAnnotation == null) {
                    continue;
                }

                String httpMethod = resolveHttpMethod(mappingAnnotation);
                String methodPath = extractPathValue(mappingAnnotation);
                String fullPath = combinePaths(classBasePath, methodPath);

                List<String> params = method.getParameters().stream()
                        .map(Parameter::getNameAsString)
                        .collect(Collectors.toList());

                String returnType = method.getType().toString();

                endpoints.add(new EndpointInfo(
                        fullPath, httpMethod, className,
                        method.getNameAsString(), params, returnType
                ));
            }
        }

        return endpoints;
    }

    private Optional<ClassOrInterfaceDeclaration> findControllerClass(CompilationUnit cu) {
        return cu.findAll(ClassOrInterfaceDeclaration.class).stream()
                .filter(c -> c.getAnnotationByClass(org.springframework.web.bind.annotation.RestController.class).isPresent()
                        || c.getAnnotationByName("RestController").isPresent())
                .findFirst();
    }

    private String extractClassBasePath(ClassOrInterfaceDeclaration clazz) {
        Optional<AnnotationExpr> mapping = clazz.getAnnotationByName("RequestMapping");
        if (mapping.isEmpty()) {
            mapping = clazz.getAnnotationByClass(org.springframework.web.bind.annotation.RequestMapping.class);
        }
        return mapping.map(this::extractPathValue).orElse("");
    }

    private AnnotationExpr findMappingAnnotation(MethodDeclaration method) {
        for (String ann : REQUEST_MAPPING_ANNOTATIONS) {
            Optional<AnnotationExpr> found = method.getAnnotationByName(ann);
            if (found.isPresent()) {
                return found.get();
            }
        }
        return null;
    }

    private String resolveHttpMethod(AnnotationExpr annotation) {
        String name = annotation.getNameAsString();
        return switch (name) {
            case "GetMapping" -> "GET";
            case "PostMapping" -> "POST";
            case "PutMapping" -> "PUT";
            case "DeleteMapping" -> "DELETE";
            case "PatchMapping" -> "PATCH";
            default -> "";
        };
    }

    private String extractPathValue(AnnotationExpr annotation) {
        if (annotation instanceof NormalAnnotationExpr normalAnnotation) {
            for (MemberValuePair pair : normalAnnotation.getPairs()) {
                String key = pair.getNameAsString();
                if ("value".equals(key) || "path".equals(key)) {
                    String raw = pair.getValue().toString();
                    return raw.replaceAll("[\"{}\\s]", "");
                }
            }
            return "";
        }
        if (annotation instanceof SingleMemberAnnotationExpr singleMember) {
            String raw = singleMember.getMemberValue().toString();
            return raw.replaceAll("[\"{}\\s]", "");
        }
        return "";
    }

    private String combinePaths(String base, String methodPath) {
        if (base == null || base.isEmpty()) {
            return normalizePath(methodPath);
        }
        if (methodPath == null || methodPath.isEmpty()) {
            return normalizePath(base);
        }
        return normalizePath(base + "/" + methodPath);
    }

    private String normalizePath(String path) {
        if (path == null || path.isEmpty()) {
            return "/";
        }
        String normalized = path.trim();
        normalized = normalized.replaceAll("/{2,}", "/");
        if (!normalized.startsWith("/")) {
            normalized = "/" + normalized;
        }
        if (normalized.endsWith("/") && normalized.length() > 1) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }
}
