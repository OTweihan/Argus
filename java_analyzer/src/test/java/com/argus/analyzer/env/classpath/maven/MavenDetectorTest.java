package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.MavenConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@link MavenDetector} 探测链单测（J4）：mock 版本检查器 + 注入环境变量，
 * 覆盖项目本地 wrapper 优先级、MAVEN_HOME/M2_HOME 兄弟目录回退，以及
 * Windows {@code ;} 与 Unix {@code :} 两种 PATH 分隔符。
 */
@DisplayName("MavenDetector detection chain")
class MavenDetectorTest {

    @TempDir
    Path tempDir;

    private MavenVersionChecker versionChecker;
    private Map<String, String> env;
    private MavenConfig config;

    /** 环境变量可控的探测器：getEnv 注入，避免依赖真实 MAVEN_HOME/PATH。 */
    private static final class TestDetector extends MavenDetector {
        private final Map<String, String> env;

        TestDetector(MavenVersionChecker checker, Map<String, String> env) {
            super(checker);
            this.env = env;
        }

        @Override
        String getEnv(String name) {
            return env.get(name);
        }
    }

    @BeforeEach
    void setUp() {
        versionChecker = mock(MavenVersionChecker.class);
        env = new HashMap<>();
        config = new MavenConfig();
    }

    private MavenDetector detector() {
        return new TestDetector(versionChecker, env);
    }

    private static Path touch(Path file) throws IOException {
        Files.createDirectories(file.getParent());
        Files.writeString(file, "");
        return file;
    }

    // ====== 项目本地 wrapper（步骤 1/2）======

    @Test
    @DisplayName("Project-local mvnw.cmd wins over everything when it is Maven 3.x")
    void prefersWindowsWrapper() throws IOException {
        Path wrapper = touch(tempDir.resolve("mvnw.cmd"));
        env.put("MAVEN_HOME", tempDir.resolve("elsewhere").toString());
        when(versionChecker.isMaven3x(anyString())).thenReturn(true);

        assertThat(detector().detect(tempDir, config))
                .isEqualTo(wrapper.toAbsolutePath().toString());
    }

    @Test
    @DisplayName("Falls back to unix mvnw wrapper when mvnw.cmd is missing")
    void fallsBackToUnixWrapper() throws IOException {
        Path wrapper = touch(tempDir.resolve("mvnw"));
        when(versionChecker.isMaven3x(anyString())).thenReturn(true);

        assertThat(detector().detect(tempDir, config))
                .isEqualTo(wrapper.toAbsolutePath().toString());
    }

    @Test
    @DisplayName("Skips wrapper pointing to Maven 4+ and uses user-specified executable")
    void skipsNon3xWrapperToConfigExecutable() throws IOException {
        touch(tempDir.resolve("mvnw.cmd"));
        when(versionChecker.isMaven3x(anyString())).thenReturn(false);
        config.setExecutable("custom-mvn");

        assertThat(detector().detect(tempDir, config)).isEqualTo("custom-mvn");
    }

    // ====== MAVEN_HOME 与兄弟目录（步骤 4-6）======

    @Test
    @DisplayName("MAVEN_HOME bin/mvn.cmd is preferred over bin/mvn")
    void mavenHomeBinCmdPreferred() throws IOException {
        Path home = tempDir.resolve("apache-maven-3.9.6");
        Path binCmd = touch(home.resolve("bin/mvn.cmd"));
        touch(home.resolve("bin/mvn"));
        env.put("MAVEN_HOME", home.toString());
        when(versionChecker.isMaven3x(anyString())).thenReturn(true);

        String detected = detector().detect(tempDir, config);
        assertThat(Path.of(detected)).isEqualTo(binCmd.toAbsolutePath());
    }

    @Test
    @DisplayName("Scans sibling directories when MAVEN_HOME points to Maven 4+")
    void scansSiblingsWhenHomeIsMaven4() throws IOException {
        Path parent = tempDir.resolve("tools");
        Path maven4 = touch(parent.resolve("apache-maven-4.0.0/bin/mvn"));
        Path maven3 = touch(parent.resolve("apache-maven-3.9.6/bin/mvn"));
        env.put("MAVEN_HOME", parent.resolve("apache-maven-4.0.0").toString());
        // 仅 apache-maven-4.0.0 判为 4.x；兄弟目录里的 3.x 通过过滤
        when(versionChecker.isMaven3x(maven4.toAbsolutePath().toString())).thenReturn(false);
        when(versionChecker.isMaven3x(org.mockito.ArgumentMatchers.contains("maven-3"))).thenReturn(true);

        String detected = detector().detect(tempDir, config);
        assertThat(detected).contains("maven-3");
        assertThat(Path.of(detected)).isEqualTo(maven3.toAbsolutePath());
    }

    @Test
    @DisplayName("Returns null when no candidate exists anywhere")
    void returnsNullWhenNothingFound() {
        when(versionChecker.isMaven3x(anyString())).thenReturn(true);

        assertThat(detector().detect(tempDir, config)).isNull();
    }

    // ====== PATH 查找与平台分隔符（步骤 7）======

    @Test
    @DisplayName("findOnPath splits Windows-style PATH entries on ';'")
    void findOnPathSplitsOnSemicolon(@TempDir Path pathRoot) throws IOException {
        Path first = Files.createDirectories(pathRoot.resolve("d1"));
        Path second = Files.createDirectories(pathRoot.resolve("d2"));
        Path mvnCmd = touch(second.resolve("mvn.cmd"));

        String pathEnv = first.toAbsolutePath() + ";" + second.toAbsolutePath();
        String found = MavenDetector.findOnPath(pathEnv, ";", "mvn.cmd");

        assertThat(found).isNotNull();
        assertThat(Paths.get(found)).isEqualTo(mvnCmd.toAbsolutePath());
    }

    @Test
    @DisplayName("findOnPath splits Unix-style PATH entries on ':'")
    void findOnPathSplitsOnColon() throws IOException {
        // 相对条目按进程 CWD 解析（surefire 以模块 basedir 为 CWD）：用 target/ 下
        // 的相对路径构造不含 ':' 的条目，在任意平台上验证 ':' 分隔语义。
        String caseId = "path-test-" + java.util.UUID.randomUUID();
        Path entryA = Files.createDirectories(Path.of("target", caseId, "d1"));
        Path entryB = Files.createDirectories(Path.of("target", caseId, "d2"));
        Path mvn = touch(entryB.resolve("mvn"));

        String found = MavenDetector.findOnPath(entryA + ":" + entryB, ":", "mvn");

        assertThat(found).isNotNull();
        assertThat(Paths.get(found)).isEqualTo(mvn.toAbsolutePath());
    }

    @Test
    @DisplayName("findOnPath skips non-existent entries and returns null when nothing matches")
    void findOnPathReturnsNullWhenNothingMatches() {
        assertThat(MavenDetector.findOnPath(
                tempDir.toString() + ";" + tempDir.resolve("missing"), ";", "mvn")).isNull();
        assertThat(MavenDetector.findOnPath(null, ";", "mvn")).isNull();
        assertThat(MavenDetector.findOnPath(tempDir.toString(), null, "mvn")).isNull();
    }

    @Test
    @DisplayName("detect uses PATH (via injected env) with last-resort fallback to any mvn")
    void detectUsesInjectedPathEnv() throws IOException {
        Path pathDir = Files.createDirectories(tempDir.resolve("on-path"));
        Path mvnCmd = touch(pathDir.resolve("mvn.cmd"));
        env.put("PATH", pathDir.toAbsolutePath().toString());
        // mvn.cmd 非 3.x → 步骤 8 last-resort 仍返回它
        when(versionChecker.isMaven3x(anyString())).thenReturn(false);

        String detected = detector().detect(tempDir, config);
        assertThat(Path.of(detected)).isEqualTo(mvnCmd.toAbsolutePath());
    }
}
