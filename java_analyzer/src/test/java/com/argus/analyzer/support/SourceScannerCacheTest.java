package com.argus.analyzer.support;

import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.MavenModuleScanner;
import com.argus.analyzer.env.MavenProjectLocator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * J10：SourceScannerCache 由单槽缓存改为按 sourcePath 键控的 Map（带容量上限）。
 * 覆盖：多项目不再互相覆盖、getModuleIndex 不再依赖先调 getSourceDirectories、
 * 非 Maven 项目返回 null 索引但 source dirs 有效。
 */
class SourceScannerCacheTest {

    @TempDir
    Path tempDir;

    private SourceScannerCache newCache() {
        return new SourceScannerCache(new MavenProjectLocator(), new MavenModuleScanner());
    }

    private void writePom(Path dir, String artifactId) throws IOException {
        Files.createDirectories(dir.resolve("src/main/java"));
        Files.writeString(dir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.han</groupId>
                  <artifactId>%s</artifactId>
                  <version>1.0</version>
                </project>
                """.formatted(artifactId));
        Files.writeString(dir.resolve("src/main/java/App.java"),
                "package com.han; public class App {}");
    }

    @Test
    void mavenProjectReturnsModuleIndexWithoutPriorSourceDirCall() throws IOException {
        Path proj = tempDir.resolve("maven-proj");
        writePom(proj, "app");

        SourceScannerCache cache = newCache();

        // 旧单槽缓存里 getModuleIndex 隐式依赖先调 getSourceDirectories 才能命中；
        // 新 Map 缓存应直接返回模块索引。
        MavenModuleIndex index = cache.getModuleIndex(proj);
        assertThat(index).isNotNull();
        assertThat(index.getNonAggregatorModuleCount()).isPositive();

        List<Path> dirs = cache.getSourceDirectories(proj);
        assertThat(dirs).isNotEmpty();
        assertThat(dirs.get(0).toString().replace('\\', '/')).endsWith("src/main/java");
    }

    @Test
    void nonMavenProjectReturnsNullIndexButValidSourceDirs() throws IOException {
        Path proj = tempDir.resolve("plain-proj");
        Files.createDirectories(proj.resolve("src/main/java"));
        Files.writeString(proj.resolve("src/main/java/A.java"), "public class A {}");

        SourceScannerCache cache = newCache();

        assertThat(cache.getModuleIndex(proj)).isNull();
        List<Path> dirs = cache.getSourceDirectories(proj);
        assertThat(dirs).hasSize(1);
        assertThat(dirs.get(0).toString().replace('\\', '/')).endsWith("src/main/java");
    }

    @Test
    void doesNotCrossContaminateBetweenProjects() throws IOException {
        Path a = tempDir.resolve("proj-a");
        writePom(a, "a");
        Path b = tempDir.resolve("proj-b");
        Files.createDirectories(b.resolve("src/main/java"));
        Files.writeString(b.resolve("src/main/java/B.java"), "public class B {}");

        SourceScannerCache cache = newCache();

        MavenModuleIndex idxA = cache.getModuleIndex(a);
        assertThat(idxA).isNotNull();

        // 访问非 Maven 项目 b（旧单槽缓存会把 a 的条目覆盖为 b 的空索引）
        assertThat(cache.getModuleIndex(b)).isNull();

        // a 的模块索引必须仍在（不被 b 的访问覆盖）
        MavenModuleIndex idxA2 = cache.getModuleIndex(a);
        assertThat(idxA2).isNotNull();
        assertThat(cache.getSourceDirectories(a)).isNotEmpty();
    }
}
