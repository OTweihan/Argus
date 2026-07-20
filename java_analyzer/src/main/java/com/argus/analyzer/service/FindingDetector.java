package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.FindingItem;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.TryStmt;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

@Service
public class FindingDetector {

    private static final Logger log = LoggerFactory.getLogger(FindingDetector.class);

    private static final Pattern URL_PATTERN = Pattern.compile(
            "https?://[\\w][\\w.-]+\\.[a-zA-Z]{2,}(:\\d+)?(/[\\w./%-]*)?",
            Pattern.CASE_INSENSITIVE
    );

    private final SourceFileScanner sourceFileScanner;

    public FindingDetector(SourceFileScanner sourceFileScanner) {
        this.sourceFileScanner = sourceFileScanner;
    }

    public List<FindingItem> detect(Path sourcePath) {
        return detect(sourcePath, List.of());
    }

    public List<FindingItem> detect(Path sourcePath, List<Path> classpathJars) {
        List<FindingItem> findings = new ArrayList<>();

        for (var entry : sourceFileScanner.scan(sourcePath, null, classpathJars).parsedFiles()) {
            Path javaFile = entry.getKey();
            CompilationUnit cu = entry.getValue();
            String relativePath = SourceFileScanner.relativize(sourcePath, javaFile);

            detectEmptyCatches(cu, relativePath, findings);
            detectHardcodedUrls(cu, relativePath, findings);
            detectSystemOut(cu, relativePath, findings);
            detectPrintStackTrace(cu, relativePath, findings);
        }

        return findings;
    }

    private void detectEmptyCatches(CompilationUnit cu, String filePath, List<FindingItem> findings) {
        for (TryStmt tryStmt : cu.findAll(TryStmt.class)) {
            for (CatchClause catchClause : tryStmt.getCatchClauses()) {
                var body = catchClause.getBody();
                if (body.getStatements() == null || body.getStatements().isEmpty()) {
                    int line = catchClause.getBegin().map(p -> p.line).orElse(0);
                    findings.add(new FindingItem(
                            "EMPTY_CATCH", "MEDIUM",
                            "空 catch 块",
                            "catch 块为空，异常被静默吞没",
                            filePath, line, "catch (" + catchClause.getParameter().getType() + " ...) {}"
                    ));
                }
            }
        }
    }

    private void detectHardcodedUrls(CompilationUnit cu, String filePath, List<FindingItem> findings) {
        for (StringLiteralExpr str : cu.findAll(StringLiteralExpr.class)) {
            String value = str.asString();
            if (URL_PATTERN.matcher(value).matches()) {
                int line = str.getBegin().map(p -> p.line).orElse(0);
                findings.add(new FindingItem(
                        "HARDCODED_URL", "LOW",
                        "硬编码 URL",
                        "URL 地址应抽取到配置文件中",
                        filePath, line, "\"" + value + "\""
                ));
            }
        }
    }

    private void detectSystemOut(CompilationUnit cu, String filePath, List<FindingItem> findings) {
        for (MethodCallExpr call : cu.findAll(MethodCallExpr.class)) {
            if ("println".equals(call.getNameAsString()) || "print".equals(call.getNameAsString())) {
                call.getScope().ifPresent(scope -> {
                    if (scope.toString().equals("System.out") || scope.toString().equals("System.err")) {
                        int line = call.getBegin().map(p -> p.line).orElse(0);
                        findings.add(new FindingItem(
                                "SYSTEM_OUT", "INFO",
                                "直接使用 System.out 输出",
                                "应使用日志框架（SLF4J/Logback）替代 System.out",
                                filePath, line, "System.out.println(...)"
                        ));
                    }
                });
            }
        }
    }

    private void detectPrintStackTrace(CompilationUnit cu, String filePath, List<FindingItem> findings) {
        for (MethodCallExpr call : cu.findAll(MethodCallExpr.class)) {
            if ("printStackTrace".equals(call.getNameAsString())) {
                int line = call.getBegin().map(p -> p.line).orElse(0);
                findings.add(new FindingItem(
                        "PRINT_STACKTRACE", "INFO",
                        "直接调用 printStackTrace",
                        "应使用日志框架记录异常堆栈",
                        filePath, line, "e.printStackTrace()"
                ));
            }
        }
    }
}
