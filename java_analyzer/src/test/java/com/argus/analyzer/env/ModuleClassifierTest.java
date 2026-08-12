package com.argus.analyzer.env;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ModuleClassifierTest {

    @TempDir
    Path tempDir;

    @Test
    void applicationModuleHasSpringBootAndMain() throws IOException {
        // han-admin: @SpringBootApplication + main
        Path moduleDir = tempDir.resolve("han-modules/han-admin");
        writeApplicationClass(moduleDir);

        MavenModuleIndex index = buildIndex(moduleDir, "han-admin");
        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);

        List<MavenModule> targets = classifier.selectTargets(index);
        assertThat(targets).hasSize(1);
        assertThat(targets.get(0).getModuleType()).isEqualTo(ModuleType.APPLICATION);
    }

    @Test
    void businessModuleHasRestControllerWithoutMain() throws IOException {
        // han-system: @RestController but no main
        Path moduleDir = tempDir.resolve("han-modules/han-system");
        writeRestController(moduleDir);

        MavenModuleIndex index = buildIndex(moduleDir, "han-system");
        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);

        List<MavenModule> targets = classifier.selectTargets(index);
        assertThat(targets).hasSize(1);
        assertThat(targets.get(0).getModuleType()).isEqualTo(ModuleType.BUSINESS);
    }

    @Test
    void commonLibraryModuleIsNotTarget() throws IOException {
        // han-common-core: no controller, artifactId contains "common"
        Path moduleDir = tempDir.resolve("han-common/han-common-core");
        writeUtilityClass(moduleDir);

        MavenModuleIndex index = buildIndex(moduleDir, "han-common-core");
        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);

        List<MavenModule> targets = classifier.selectTargets(index);
        assertThat(targets).isEmpty();

        MavenModule module = index.findModule("han-common-core").orElseThrow();
        assertThat(module.getModuleType()).isEqualTo(ModuleType.LIBRARY);
    }

    @Test
    void commonModuleWithRestControllerIsStillTarget() throws IOException {
        // han-common-web: artifactId contains "common" BUT has @RestController → BUSINESS
        Path moduleDir = tempDir.resolve("han-common/han-common-web");
        writeRestController(moduleDir);

        MavenModuleIndex index = buildIndex(moduleDir, "han-common-web");
        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);

        List<MavenModule> targets = classifier.selectTargets(index);
        assertThat(targets).isNotEmpty();
        assertThat(targets.get(0).getModuleType()).isEqualTo(ModuleType.BUSINESS);
    }

    @Test
    void aggregatorModuleIsNotTarget() throws IOException {
        // Root POM: packaging=pom, no sources
        writePom(tempDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.test</groupId>
                  <artifactId>parent</artifactId>
                  <version>1.0.0</version>
                  <packaging>pom</packaging>
                </project>
                """);

        MavenModuleIndex index = new MavenModuleScanner().scan(tempDir.resolve("pom.xml"));

        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);
        List<MavenModule> targets = classifier.selectTargets(index);

        assertThat(targets).isEmpty();

        MavenModule module = index.findModule("parent").orElseThrow();
        assertThat(module.getModuleType()).isEqualTo(ModuleType.AGGREGATOR);
    }

    @Test
    void bomModuleIsAggregating() throws IOException {
        writePom(tempDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.test</groupId>
                  <artifactId>test-bom</artifactId>
                  <version>1.0.0</version>
                  <packaging>pom</packaging>
                </project>
                """);

        MavenModuleIndex index = new MavenModuleScanner().scan(tempDir.resolve("pom.xml"));

        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);

        MavenModule module = index.findModule("test-bom").orElseThrow();
        assertThat(module.getModuleType()).isEqualTo(ModuleType.BOM);
    }

    @Test
    void selectTargetsPrioritizesApplicationOverBusiness() throws IOException {
        // Module A: application (has SpringBoot + main)
        Path appDir = tempDir.resolve("app");
        writeApplicationClass(appDir);
        writePom(appDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <parent>
                    <groupId>com.test</groupId>
                    <artifactId>parent</artifactId>
                    <version>1.0.0</version>
                  </parent>
                  <artifactId>app-module</artifactId>
                </project>
                """);

        // Module B: business (has controller, no main)
        Path bizDir = tempDir.resolve("biz");
        writeRestController(bizDir);
        writePom(bizDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <parent>
                    <groupId>com.test</groupId>
                    <artifactId>parent</artifactId>
                    <version>1.0.0</version>
                  </parent>
                  <artifactId>biz-module</artifactId>
                </project>
                """);

        writePom(tempDir.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.test</groupId>
                  <artifactId>parent</artifactId>
                  <version>1.0.0</version>
                  <packaging>pom</packaging>
                  <modules>
                    <module>app</module>
                    <module>biz</module>
                  </modules>
                </project>
                """);

        MavenModuleIndex index = new MavenModuleScanner().scan(tempDir.resolve("pom.xml"));

        ModuleClassifier classifier = new ModuleClassifier();
        classifier.classifyAll(index);
        List<MavenModule> targets = classifier.selectTargets(index);

        assertThat(targets).hasSize(2);
        assertThat(targets.get(0).getModuleType()).isEqualTo(ModuleType.APPLICATION);
        assertThat(targets.get(1).getModuleType()).isEqualTo(ModuleType.BUSINESS);
    }

    @Test
    void concurrentClassifyAllDoesNotCrossPolluteSignalsCache() throws Exception {
        // 两个独立索引并发分类/选目标，结果必须与单线程基线一致。
        // 回归 J-H2：_signalsCache 若为共享 HashMap，A 作业 clear()/put() 会与
        // B 作业 getOrDefault() 竞争，导致错误分类或丢缓存；ThreadLocal 隔离后
        // 每个作业线程只看到自己的缓存。
        Path dirA = tempDir.resolve("index-a");
        Path dirB = tempDir.resolve("index-b");
        writeApplicationClass(dirA.resolve("a-app"));
        writeRestController(dirA.resolve("a-biz"));
        writeRestController(dirB.resolve("b-app"));
        writePom(dirA.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.test</groupId>
                  <artifactId>parent-a</artifactId>
                  <version>1.0.0</version>
                  <packaging>pom</packaging>
                  <modules><module>a-app</module><module>a-biz</module></modules>
                </project>
                """);
        writePom(dirB.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.test</groupId>
                  <artifactId>parent-b</artifactId>
                  <version>1.0.0</version>
                  <packaging>pom</packaging>
                  <modules><module>b-app</module></modules>
                </project>
                """);

        MavenModuleIndex indexA = new MavenModuleScanner().scan(dirA.resolve("pom.xml"));
        MavenModuleIndex indexB = new MavenModuleScanner().scan(dirB.resolve("pom.xml"));

        // 单线程基线
        ModuleClassifier baseline = new ModuleClassifier();
        baseline.classifyAll(indexA);
        var baselineA = baseline.selectTargets(indexA);
        baseline.classifyAll(indexB);
        var baselineB = baseline.selectTargets(indexB);

        // 共享 classifier 上双线程并发（每线程各自 classifyAll → selectTargets）
        ModuleClassifier shared = new ModuleClassifier();
        List<Throwable> failures = new java.util.concurrent.CopyOnWriteArrayList<>();
        Runnable taskA = () -> {
            try {
                shared.classifyAll(indexA);
                var targets = shared.selectTargets(indexA);
                assertTargetTypesEqual(baselineA, targets);
            } catch (Throwable t) {
                failures.add(t);
            }
        };
        Runnable taskB = () -> {
            try {
                shared.classifyAll(indexB);
                var targets = shared.selectTargets(indexB);
                assertTargetTypesEqual(baselineB, targets);
            } catch (Throwable t) {
                failures.add(t);
            }
        };
        var pool = java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            var f1 = pool.submit(taskA);
            var f2 = pool.submit(taskB);
            f1.get();
            f2.get();
        } finally {
            pool.shutdownNow();
        }
        assertThat(failures).isEmpty();
    }

    private static void assertTargetTypesEqual(List<MavenModule> expected, List<MavenModule> actual) {
        assertThat(actual.stream().map(MavenModule::getModuleType).toList())
                .containsExactlyElementsOf(expected.stream().map(MavenModule::getModuleType).toList());
    }

    // ====== 辅助方法 ======

    private MavenModuleIndex buildIndex(Path moduleDir, String artifactId) throws IOException {
        writePom(moduleDir.resolve("pom.xml"), String.format("""
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>com.test</groupId>
                  <artifactId>%s</artifactId>
                  <version>1.0.0</version>
                </project>
                """, artifactId));
        return new MavenModuleScanner().scan(moduleDir.resolve("pom.xml"));
    }

    private void writeApplicationClass(Path moduleDir) throws IOException {
        Path src = moduleDir.resolve("src/main/java/com/test/App.java");
        Files.createDirectories(src.getParent());
        Files.writeString(src, """
                package com.test;
                import org.springframework.boot.autoconfigure.SpringBootApplication;
                @SpringBootApplication
                public class App {
                    public static void main(String[] args) {}
                }
                """);
    }

    private void writeRestController(Path moduleDir) throws IOException {
        Path src = moduleDir.resolve("src/main/java/com/test/Controller.java");
        Files.createDirectories(src.getParent());
        Files.writeString(src, """
                package com.test;
                import org.springframework.web.bind.annotation.RestController;
                @RestController
                public class Controller {
                    public String hello() { return "ok"; }
                }
                """);
    }

    private void writeUtilityClass(Path moduleDir) throws IOException {
        Path src = moduleDir.resolve("src/main/java/com/test/Util.java");
        Files.createDirectories(src.getParent());
        Files.writeString(src, """
                package com.test;
                public class Util {
                    public static String format(String s) { return s.trim(); }
                }
                """);
    }

    private void writePom(Path path, String content) throws IOException {
        Files.createDirectories(path.getParent());
        Files.writeString(path, content);
    }
}
