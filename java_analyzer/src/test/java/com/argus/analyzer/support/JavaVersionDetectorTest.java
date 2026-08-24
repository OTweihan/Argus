package com.argus.analyzer.support;

import com.github.javaparser.ParserConfiguration;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link JavaVersionDetector} 单测（J4）：锁定 pom（release/source/java.version）
 * 与 gradle（sourceCompatibility）的版本解析、优先级和默认值行为。
 */
@DisplayName("JavaVersionDetector build-file parsing")
class JavaVersionDetectorTest {

    @TempDir
    Path tempDir;

    private Path writePom(String properties) throws IOException {
        Path pom = tempDir.resolve("pom.xml");
        Files.writeString(pom, """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  %s
                </project>
                """.formatted(properties));
        return pom;
    }

    private Path writeGradle(String line) throws IOException {
        Path gradle = tempDir.resolve("build.gradle");
        Files.writeString(gradle, """
                plugins { id 'java' }
                %s
                """.formatted(line));
        return gradle;
    }

    @Test
    @DisplayName("maven.compiler.release takes precedence over source and java.version")
    void pomReleaseWins() throws IOException {
        writePom("""
                  <properties>
                    <maven.compiler.release>21</maven.compiler.release>
                    <maven.compiler.source>11</maven.compiler.source>
                    <java.version>8</java.version>
                  </properties>
                """);

        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(21);
        assertThat(JavaVersionDetector.detect(tempDir))
                .isEqualTo(ParserConfiguration.LanguageLevel.JAVA_21);
    }

    @Test
    @DisplayName("maven.compiler.source used when release absent")
    void pomSourceSecondPriority() throws IOException {
        writePom("""
                  <properties>
                    <maven.compiler.source>11</maven.compiler.source>
                    <java.version>8</java.version>
                  </properties>
                """);

        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(11);
    }

    @Test
    @DisplayName("<java.version> property parsed (classic Boot parent style)")
    void pomJavaVersionProperty() throws IOException {
        writePom("""
                  <properties><java.version>8</java.version></properties>
                """);

        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(8);
        assertThat(JavaVersionDetector.detect(tempDir))
                .isEqualTo(ParserConfiguration.LanguageLevel.JAVA_8);
    }

    @Test
    @DisplayName("Property matching is case-insensitive")
    void propertyMatchingCaseInsensitive() throws IOException {
        writePom("""
                  <properties><JAVA.VERSION>13</JAVA.VERSION></properties>
                """);

        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(13);
    }

    @Test
    @DisplayName("gradle sourceCompatibility parsed in quoted and unquoted forms")
    void gradleSourceCompatibilityForms() throws IOException {
        writeGradle("sourceCompatibility = '17'");
        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(17);

        writeGradle("sourceCompatibility = \"16\"");
        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(16);

        writeGradle("sourceCompatibility = 11");
        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(11);
    }

    @Test
    @DisplayName("pom.xml preferred over build.gradle when both exist")
    void pomPreferredOverGradle() throws IOException {
        writePom("""
                  <properties><maven.compiler.release>17</maven.compiler.release></properties>
                """);
        writeGradle("sourceCompatibility = 11");

        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(17);
    }

    @Test
    @DisplayName("Unknown or missing versions default to JAVA_17")
    void defaultsToJava17(@TempDir Path emptyDir) throws IOException {
        // 无构建文件：detectVersion=0，detect 默认 JAVA_17
        assertThat(JavaVersionDetector.detectVersion(emptyDir)).isZero();
        assertThat(JavaVersionDetector.detect(emptyDir))
                .isEqualTo(ParserConfiguration.LanguageLevel.JAVA_17);

        // 超出映射表的版本同样回落 JAVA_17
        writePom("""
                  <properties><maven.compiler.release>40</maven.compiler.release></properties>
                """);
        assertThat(JavaVersionDetector.detectVersion(tempDir)).isEqualTo(40);
        assertThat(JavaVersionDetector.detect(tempDir))
                .isEqualTo(ParserConfiguration.LanguageLevel.JAVA_17);
    }
}
