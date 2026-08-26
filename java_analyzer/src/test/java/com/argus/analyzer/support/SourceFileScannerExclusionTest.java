package com.argus.analyzer.support;

import com.argus.analyzer.env.MavenModuleScanner;
import com.argus.analyzer.env.MavenProjectLocator;
import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 扫描输入排除口径（测试源码 / 构建输出，单一事实源
 * {@link BuildOutputFilter#isExcludedFromAnalysis}）与解析并行化的行为契约。
 *
 * <p>关键回归点：测试源码 {@code src/test/**} 不再被解析进入端点/缺陷结果；
 * 指纹与扫描同口径——只改测试代码不得使缓存键漂移；并行分片输出确定。</p>
 */
class SourceFileScannerExclusionTest {

    @TempDir
    Path tempDir;

    private void write(Path file, String content) throws IOException {
        Files.createDirectories(file.getParent());
        Files.writeString(file, content);
    }

    private SourceFileScanner newScanner(int parseThreads) {
        return new SourceFileScanner(
                new JavaParser(new ParserConfiguration()),
                new SourceScannerCache(new MavenProjectLocator(), new MavenModuleScanner()),
                new JarTypeSolverPool(),
                parseThreads);
    }

    private Path newProject() throws IOException {
        Path proj = tempDir.resolve("proj");
        write(proj.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.han</groupId>
                  <artifactId>app</artifactId>
                  <version>1.0</version>
                </project>
                """);
        return proj;
    }

    @Test
    void excludesTestSourcesAndBuildOutputFromScan() throws IOException {
        Path proj = newProject();
        write(proj.resolve("src/main/java/com/han/Main.java"),
                "package com.han; public class Main {}");
        // 测试 fixture 的 @RestController 类代码会制造假端点，必须整体排除
        write(proj.resolve("src/test/java/com/han/MainTest.java"),
                "package com.han; public class MainTest {}");
        write(proj.resolve("target/generated-sources/com/han/Gen.java"),
                "package com.han; public class Gen {}");

        SourceFileScanner.ScanResult result = newScanner(0).scan(proj);

        assertThat(result.totalFiles()).isEqualTo(1);
        assertThat(result.parsedFiles()).hasSize(1);
        assertThat(result.parsedFiles().get(0).getKey().toString().replace('\\', '/'))
                .endsWith("src/main/java/com/han/Main.java");
    }

    @Test
    void parallelScanIsDeterministicAcrossRuns() throws IOException {
        Path proj = newProject();
        int fileCount = 48;
        for (int i = 0; i < fileCount; i++) {
            write(proj.resolve("src/main/java/com/han/Type" + i + ".java"),
                    "package com.han; public class Type" + i + " {}");
        }
        SourceFileScanner scanner = newScanner(4);

        SourceFileScanner.ScanResult first = scanner.scan(proj);
        SourceFileScanner.ScanResult second = scanner.scan(proj);

        assertThat(first.totalFiles()).isEqualTo(fileCount);
        assertThat(first.parsedFiles()).hasSize(fileCount);
        List<String> firstOrder =
                first.parsedFiles().stream().map(entry -> entry.getKey().toString()).toList();
        List<String> secondOrder =
                second.parsedFiles().stream().map(entry -> entry.getKey().toString()).toList();
        assertThat(secondOrder).isEqualTo(firstOrder);
    }

    @Test
    void fingerprintIgnoresTestOnlyChangesButReactToMainChanges() throws IOException {
        Path proj = newProject();
        Path main = proj.resolve("src/main/java/com/han/Main.java");
        write(main, "package com.han; public class Main {}");
        write(proj.resolve("src/test/java/com/han/MainTest.java"),
                "package com.han; public class MainTest {}");

        String baseline = SourceFingerprint.compute(proj);

        // 仅测试代码变化：缓存键身份不变
        write(proj.resolve("src/test/java/com/han/MainTest.java"),
                "package com.han; public class MainTest { void m() {} }");
        assertThat(SourceFingerprint.compute(proj)).isEqualTo(baseline);

        // 主源码变化：缓存键必须变化
        write(main, "package com.han; public class Main { void go() {} }");
        assertThat(SourceFingerprint.compute(proj)).isNotEqualTo(baseline);
    }
}
