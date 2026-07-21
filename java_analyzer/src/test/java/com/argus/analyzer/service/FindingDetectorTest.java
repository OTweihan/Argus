package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.FindingItem;
import com.argus.analyzer.env.MavenModuleScanner;
import com.argus.analyzer.env.MavenProjectLocator;
import com.argus.analyzer.support.SourceFileScanner;
import com.argus.analyzer.support.SourceScannerCache;
import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class FindingDetectorTest {

    @TempDir
    Path tempDir;

    private FindingDetector detector;

    @BeforeEach
    void setUp() throws IOException {
        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        detector = new FindingDetector(new SourceFileScanner(
            new JavaParser(config),
            new SourceScannerCache(new MavenProjectLocator(), new MavenModuleScanner())
        ));
        createTestFiles(tempDir);
    }

    @Test
    void shouldDetectEmptyCatch() {
        List<FindingItem> findings = detector.detect(tempDir);
        assertThat(findings)
                .filteredOn(f -> "EMPTY_CATCH".equals(f.ruleId()))
                .isNotEmpty();
    }

    @Test
    void shouldDetectHardcodedUrls() {
        List<FindingItem> findings = detector.detect(tempDir);
        assertThat(findings)
                .filteredOn(f -> "HARDCODED_URL".equals(f.ruleId()))
                .isNotEmpty();
    }

    @Test
    void shouldDetectSystemOut() {
        List<FindingItem> findings = detector.detect(tempDir);
        assertThat(findings)
                .filteredOn(f -> "SYSTEM_OUT".equals(f.ruleId()))
                .isNotEmpty();
    }

    @Test
    void shouldDetectPrintStackTrace() {
        List<FindingItem> findings = detector.detect(tempDir);
        assertThat(findings)
                .filteredOn(f -> "PRINT_STACKTRACE".equals(f.ruleId()))
                .isNotEmpty();
    }

    private void createTestFiles(Path root) throws IOException {
        String code = """
                package com.example.badcode;

                import java.io.IOException;
                import java.net.URL;

                public class BadPractices {

                    public void emptyCatch() {
                        try {
                            int x = 1 / 0;
                        } catch (ArithmeticException e) {
                            // empty catch
                        }
                    }

                    public void hardcodedUrl() throws Exception {
                        String url = "https://api.example.com/v1/users";
                        new URL(url).openConnection();
                    }

                    public void systemOut() {
                        System.out.println("debug output");
                        System.err.println("error output");
                    }

                    public void printStack() {
                        try {
                            throw new RuntimeException("test");
                        } catch (RuntimeException e) {
                            e.printStackTrace();
                        }
                    }
                }
                """;

        Path srcDir = root.resolve("src/main/java/com/example/badcode");
        Files.createDirectories(srcDir);
        Files.writeString(srcDir.resolve("BadPractices.java"), code);
    }
}
