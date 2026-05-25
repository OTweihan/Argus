package com.argus.analyzer.env;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class MavenModuleScannerTest {

    @TempDir
    Path tempDir;

    @Test
    void shouldReadDirectArtifactIdInsteadOfParentArtifactId() throws IOException {
        writePom(tempDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.han</groupId>
                  <artifactId>WeaveHan</artifactId>
                  <version>${revision}</version>
                  <packaging>pom</packaging>
                  <modules>
                    <module>han-common</module>
                  </modules>
                </project>
                """);
        Path child = tempDir.resolve("han-common");
        writePom(child.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <parent>
                    <groupId>com.han</groupId>
                    <artifactId>han-common</artifactId>
                    <version>${revision}</version>
                  </parent>
                  <artifactId>han-common-core</artifactId>
                </project>
                """);

        MavenModuleIndex index = new MavenModuleScanner().scan(tempDir.resolve("pom.xml"));

        assertThat(index.findModule("han-common-core")).isPresent();
        MavenModule module = index.findModule("han-common-core").orElseThrow();
        assertThat(module.getArtifactId()).isEqualTo("han-common-core");
        assertThat(module.getModulePath()).isEqualTo("han-common");
        // 非聚合模块，moduleType 应为 UNKNOWN（等待 ModuleClassifier 处理）
        assertThat(module.getModuleType()).isEqualTo(ModuleType.UNKNOWN);
    }

    @Test
    void detectorShouldSkipPomAndSourceLessModulesAndReturnRelativePath() throws IOException {
        writePom(tempDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.han</groupId>
                  <artifactId>WeaveHan</artifactId>
                  <version>1.0.0</version>
                  <packaging>pom</packaging>
                  <modules>
                    <module>han-modules</module>
                    <module>han-modules/han-admin</module>
                  </modules>
                </project>
                """);
        writePom(tempDir.resolve("han-modules/pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <parent>
                    <groupId>com.han</groupId>
                    <artifactId>WeaveHan</artifactId>
                    <version>1.0.0</version>
                  </parent>
                  <artifactId>han-modules</artifactId>
                  <packaging>pom</packaging>
                </project>
                """);
        Path admin = tempDir.resolve("han-modules/han-admin");
        writePom(admin.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <parent>
                    <groupId>com.han</groupId>
                    <artifactId>WeaveHan</artifactId>
                    <version>1.0.0</version>
                  </parent>
                  <artifactId>han-admin</artifactId>
                </project>
                """);
        Path appClass = admin.resolve("src/main/java/com/han/AdminApplication.java");
        Files.createDirectories(appClass.getParent());
        Files.writeString(appClass, """
                package com.han;
                import org.springframework.boot.autoconfigure.SpringBootApplication;
                @SpringBootApplication
                public class AdminApplication {
                    public static void main(String[] args) {}
                }
                """);

        MavenModuleIndex index = new MavenModuleScanner().scan(tempDir.resolve("pom.xml"));

        assertThat(new ApplicationModuleDetector(new ModuleClassifier()).detect(index))
                .containsExactly("han-modules/han-admin");
        // 聚合模块应被标记为 AGGREGATOR
        assertThat(index.findModule("WeaveHan")).isPresent();
        assertThat(index.findModule("WeaveHan").get().getModuleType()).isEqualTo(ModuleType.AGGREGATOR);
        // 子聚合模块
        assertThat(index.findModule("han-modules")).isPresent();
        assertThat(index.findModule("han-modules").get().getModuleType()).isEqualTo(ModuleType.AGGREGATOR);
        // 应用模块应被标记为 APPLICATION（通过 ModuleClassifier）
        assertThat(index.findModule("han-admin")).isPresent();
        assertThat(index.findModule("han-admin").get().getModuleType()).isEqualTo(ModuleType.APPLICATION);
    }

    private void writePom(Path path, String content) throws IOException {
        Files.createDirectories(path.getParent());
        Files.writeString(path, content);
    }
}
