package com.argus.analyzer.service;

import com.argus.analyzer.domain.AnalysisContribution;
import com.argus.analyzer.domain.AnalysisContext;
import com.argus.analyzer.domain.AnalysisPass;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.Capability;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.domain.model.FindingItem;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.TryStmt;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 缺陷检测（O-11 起实现 {@link AnalysisPass}，无状态、线程安全）。
 */
public class FindingDetector implements AnalysisPass {

    private static final Logger log = LoggerFactory.getLogger(FindingDetector.class);

    private static final Pattern URL_PATTERN = Pattern.compile(
            "https?://[\\w][\\w.-]+\\.[a-zA-Z]{2,}(:\\d+)?(/[\\w./%-]*)?",
            Pattern.CASE_INSENSITIVE
    );

    private final SourceFileScanner sourceFileScanner;

    public FindingDetector(SourceFileScanner sourceFileScanner) {
        this.sourceFileScanner = sourceFileScanner;
    }

    @Override
    public String id() {
        return "findings";
    }

    @Override
    public Capability produced() {
        return Capability.FINDINGS;
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
        return guarded(context, () -> new AnalysisContribution(Capability.FINDINGS,
                detectFrom(sourceFileScanner.scanForContext(context), context.sourcePath(),
                        context.progress())));
    }

    public List<FindingItem> detect(Path sourcePath) {
        return detect(sourcePath, List.of());
    }

    public List<FindingItem> detect(Path sourcePath, List<Path> classpathJars) {
        return detect(sourcePath, classpathJars, AnalysisProgressListener.NOOP);
    }

    /**
     * 检测缺陷，支持协作取消（O-04）：扫描与逐文件处理的安全边界检查
     * {@code progress.isCancelled()}，取消时抛 {@link JobCancelledException}。
     */
    public List<FindingItem> detect(Path sourcePath, List<Path> classpathJars,
                                    AnalysisProgressListener progress) {
        return detectFrom(sourceFileScanner.scan(sourcePath, null, classpathJars, progress),
                sourcePath, progress);
    }

    private List<FindingItem> detectFrom(SourceFileScanner.ScanResult scanResult,
                                         Path sourcePath, AnalysisProgressListener progress) {
        List<FindingItem> findings = new ArrayList<>();

        for (var entry : scanResult.parsedFiles()) {
            if (progress.isCancelled()) {
                throw new JobCancelledException("Finding detection cancelled");
            }
            Path javaFile = entry.getKey();
            CompilationUnit cu = entry.getValue();
            String relativePath = SourceFileScanner.relativize(sourcePath, javaFile);

            // 单次 AST 遍历合并四类检测（此前分别 4 次 findAll：TryStmt /
            // StringLiteralExpr / MethodCallExpr × 2），大项目下降为一次全树遍历。
            cu.accept(new FindingVisitor(relativePath, findings), null);
        }

        return findings;
    }

    /**
     * 单次遍历的四类缺陷检测访问器：空 catch、硬编码 URL、System.out、printStackTrace。
     */
    private static final class FindingVisitor extends VoidVisitorAdapter<Void> {

        private final String filePath;
        private final List<FindingItem> findings;

        private FindingVisitor(String filePath, List<FindingItem> findings) {
            this.filePath = filePath;
            this.findings = findings;
        }

        @Override
        public void visit(TryStmt tryStmt, Void arg) {
            for (CatchClause catchClause : tryStmt.getCatchClauses()) {
                var body = catchClause.getBody();
                if (body.getStatements() == null || body.getStatements().isEmpty()) {
                    int line = catchClause.getBegin().map(p -> p.line).orElse(0);
                    findings.add(new FindingItem(
                            "EMPTY_CATCH", "MEDIUM",
                            "空 catch 块",
                            "catch 块为空，异常被静默吞没",
                            filePath, line, "catch (" + catchClause.getParameter().getType() + " ...) {}",
                            "ERROR_HANDLING", "HIGH"
                    ));
                }
            }
            super.visit(tryStmt, arg);
        }

        @Override
        public void visit(StringLiteralExpr str, Void arg) {
            String value = str.asString();
            if (URL_PATTERN.matcher(value).matches()) {
                int line = str.getBegin().map(p -> p.line).orElse(0);
                findings.add(new FindingItem(
                        "HARDCODED_URL", "LOW",
                        "硬编码 URL",
                        "URL 地址应抽取到配置文件中",
                        filePath, line, "\"" + value + "\"",
                        "SECURITY", "HIGH"
                ));
            }
            super.visit(str, arg);
        }

        @Override
        public void visit(MethodCallExpr call, Void arg) {
            String name = call.getNameAsString();
            if ("println".equals(name) || "print".equals(name)) {
                call.getScope().ifPresent(scope -> {
                    if (scope.toString().equals("System.out") || scope.toString().equals("System.err")) {
                        int line = call.getBegin().map(p -> p.line).orElse(0);
                        findings.add(new FindingItem(
                                "SYSTEM_OUT", "INFO",
                                "直接使用 System.out 输出",
                                "应使用日志框架（SLF4J/Logback）替代 System.out",
                                filePath, line, "System.out.println(...)",
                                "CODE_STYLE", "HIGH"
                        ));
                    }
                });
            } else if ("printStackTrace".equals(name)) {
                int line = call.getBegin().map(p -> p.line).orElse(0);
                findings.add(new FindingItem(
                        "PRINT_STACKTRACE", "INFO",
                        "直接调用 printStackTrace",
                        "应使用日志框架记录异常堆栈",
                        filePath, line, "e.printStackTrace()",
                        "ERROR_HANDLING", "HIGH"
                ));
            }
            super.visit(call, arg);
        }
    }
}
