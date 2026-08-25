package com.argus.analyzer.env.classpath.parser;

import com.argus.analyzer.env.ClasspathResult;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link ClasspathFileReader} 单测（J4）：锁定 Windows {@code ;} 与 Unix {@code :}
 * 分隔符选择、存在性过滤与空/缺失文件的降级行为。
 */
@DisplayName("ClasspathFileReader parsing")
class ClasspathFileReaderTest {

    private final ClasspathFileReader reader = new ClasspathFileReader();

    private static Path touch(Path file) throws IOException {
        Files.createDirectories(file.getParent());
        Files.writeString(file, "jar");
        return file.toAbsolutePath();
    }

    @Test
    @DisplayName("Picks ';' separator even when entries contain ':' (Windows absolute paths)")
    void semicolonSeparatorWinsOverColon(@TempDir Path tempDir) throws IOException {
        Path jar1 = touch(tempDir.resolve("repo/a.jar"));
        Path jar2 = touch(tempDir.resolve("repo/b.jar"));
        // Windows 绝对路径自带盘符 ':'，内容同时含 ';' 与 ':' —— 必须选 ';'
        Path classpathFile = tempDir.resolve("classpath.txt");
        Files.writeString(classpathFile, jar1 + ";" + jar2);

        ClasspathResult result = reader.read(classpathFile, "maven-test");

        assertThat(result.isAvailable()).isTrue();
        assertThat(result.isFallback()).isFalse();
        assertThat(result.getSource()).isEqualTo("maven-test");
        assertThat(result.getJars()).containsExactly(jar1.toString(), jar2.toString());
        assertThat(result.getWarnings()).isEmpty();
    }

    @Test
    @DisplayName("Falls back to ':' separator when content has no ';'")
    void colonSeparatorUsedWhenNoSemicolon(@TempDir Path tempDir) throws IOException {
        // 两个不存在的条目用 ':' 连接：若未按 ':' 拆分，warning 会包含完整串
        Path classpathFile = tempDir.resolve("classpath-unix.txt");
        Files.writeString(classpathFile, "/opt/libs/x.jar:/opt/libs/y.jar");

        ClasspathResult result = reader.read(classpathFile, "maven-test");

        assertThat(result.isAvailable()).isTrue();
        assertThat(result.getJars()).isEmpty();
        assertThat(result.getWarnings()).containsExactly(
                "JAR not found, skipping: /opt/libs/x.jar",
                "JAR not found, skipping: /opt/libs/y.jar");
    }

    @Test
    @DisplayName("Windows drive-letter single entry without ';' keeps the drive colon intact")
    void windowsSingleEntryKeepsDriveColon(@TempDir Path tempDir) throws IOException {
        // mdep build-classpath 在单依赖模块下只写一个条目（无 ';'），
        // 内容如 C:\Users\...\.m2\...\x.jar：若按 ':' 切分会被劈成
        // "C" + "\Users\..."（盘符丢失/驱动器相对路径），导致缓存永远失效。
        // 修复后整行作为单条目处理（此处断言 warning 携带完整未劈裂路径）。
        Path classpathFile = tempDir.resolve("classpath-win.txt");
        Files.writeString(
                classpathFile,
                "C:\\Users\\demo\\.m2\\repository\\com\\acme\\acme-1.0.jar");

        ClasspathResult result = reader.read(classpathFile, "maven-test");

        assertThat(result.isAvailable()).isTrue();
        assertThat(result.getWarnings()).containsExactly(
                "JAR not found, skipping: C:\\Users\\demo\\.m2\\repository\\com\\acme\\acme-1.0.jar");
        assertThat(result.getJars()).isEmpty();
    }

    @Test
    @DisplayName("Missing JARs become warnings while valid ones are kept")
    void missingJarsBecomeWarnings(@TempDir Path tempDir) throws IOException {
        Path valid = touch(tempDir.resolve("keep.jar"));
        Path classpathFile = tempDir.resolve("cp.txt");
        Files.writeString(classpathFile, valid + ";" + tempDir.resolve("ghost.jar").toAbsolutePath());

        ClasspathResult result = reader.read(classpathFile, "cache");

        assertThat(result.getJars()).containsExactly(valid.toString());
        assertThat(result.getWarnings()).hasSize(1);
        assertThat(result.getWarnings().get(0)).contains("ghost.jar").contains("not found");
    }

    @Test
    @DisplayName("Trims whitespace around entries and skips empty parts")
    void trimsWhitespaceAndSkipsEmptyParts(@TempDir Path tempDir) throws IOException {
        Path jar1 = touch(tempDir.resolve("w1.jar"));
        Path jar2 = touch(tempDir.resolve("w2.jar"));
        Path classpathFile = tempDir.resolve("cp.txt");
        Files.writeString(classpathFile, "  " + jar1 + " ; ;\n" + jar2 + " \n ");

        ClasspathResult result = reader.read(classpathFile, "maven-test");

        assertThat(result.getJars()).containsExactly(jar1.toString(), jar2.toString());
        assertThat(result.getWarnings()).isEmpty();
    }

    @Test
    @DisplayName("Empty classpath file degrades to unavailable with a warning")
    void emptyFileIsUnavailable(@TempDir Path tempDir) throws IOException {
        Path classpathFile = tempDir.resolve("empty.txt");
        Files.writeString(classpathFile, "   \n");

        ClasspathResult result = reader.read(classpathFile, "cache");

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.isFallback()).isTrue();
        assertThat(result.getErrors()).isEmpty();
        assertThat(result.getWarnings()).hasSize(1);
        assertThat(result.getWarnings().get(0)).contains("empty");
    }

    @Test
    @DisplayName("Unreadable classpath file returns unavailable with error")
    void missingFileReturnsUnavailable(@TempDir Path tempDir) {
        ClasspathResult result = reader.read(tempDir.resolve("no-such-classpath.txt"), "explicit");

        assertThat(result.isAvailable()).isFalse();
        assertThat(result.isFallback()).isTrue();
        assertThat(result.getErrors()).hasSize(1);
        assertThat(result.getWarnings()).hasSize(1);
    }
}
