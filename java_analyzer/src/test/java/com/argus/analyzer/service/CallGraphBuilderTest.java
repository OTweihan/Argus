package com.argus.analyzer.service;

import com.argus.analyzer.domain.model.CallEdge;
import com.argus.analyzer.domain.model.CallGraphNode;
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
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class CallGraphBuilderTest {

    @TempDir
    Path tempDir;

    private CallGraphBuilder builder;

    @BeforeEach
    void setUp() throws IOException {
        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        builder = new CallGraphBuilder(new SourceFileScanner(
            new JavaParser(config),
            new SourceScannerCache(new MavenProjectLocator(), new MavenModuleScanner())
        ));
        createTestProject(tempDir);
    }

    @Test
    void shouldBuildCallGraph() {
        Map<String, CallGraphNode> graph = builder.build(tempDir).graph();
        assertThat(graph).isNotEmpty();

        // Controller → Service 调用链
        CallGraphNode controllerNode = graph.get("com.example.demo.UserController#getUser");
        assertThat(controllerNode).isNotNull();
        // 符号解析器可解析同文件内的跨类调用
        assertThat(controllerNode.calleeDetails())
                .extracting(CallEdge::to)
                .contains("com.example.demo.UserService#findById");
    }

    @Test
    void shouldIncludeServiceMethods() {
        Map<String, CallGraphNode> graph = builder.build(tempDir).graph();

        CallGraphNode serviceNode = graph.get("com.example.demo.UserService#findById");
        assertThat(serviceNode).isNotNull();
        assertThat(serviceNode.methodSignature()).contains("User findById");
    }

    @Test
    void shouldExcludeTargetDirectory() throws IOException {
        // 在 target/ 下放一个文件，验证不会被扫描
        Path targetDir = tempDir.resolve("target/classes/com/example");
        Files.createDirectories(targetDir);
        Files.writeString(targetDir.resolve("Generated.java"), """
                package com.example;
                public class Generated {
                    public void generatedMethod() {}
                }
                """);

        Map<String, CallGraphNode> graph = builder.build(tempDir).graph();
        assertThat(graph).doesNotContainKey("com.example.Generated#generatedMethod");
    }

    @Test
    void shouldHandleParseFailureGracefully() throws IOException {
        // 放一个不可解析的文件，验证不会抛异常
        Path invalidDir = tempDir.resolve("src/main/java/com/example");
        Files.createDirectories(invalidDir);
        Files.writeString(invalidDir.resolve("Broken.java"), "this is not valid java code");

        Map<String, CallGraphNode> graph = builder.build(tempDir).graph();
        // 可解析的文件仍然正常
        assertThat(graph).isNotEmpty();
    }

    @Test
    void shouldKeepOverloadedMethodsAsDistinctNodes() throws IOException {
        Path srcDir = tempDir.resolve("src/main/java/com/example/demo");
        Files.createDirectories(srcDir);
        Files.writeString(srcDir.resolve("Overloaded.java"), """
                package com.example.demo;

                public class Overloaded {
                    public String foo(int value) { return "int"; }
                    public String foo(String value) { return "str"; }
                }
                """);

        Map<String, CallGraphNode> graph = builder.build(tempDir).graph();

        // 重载不再互相覆盖：名字键保留首个重载，后续重载使用签名键
        assertThat(graph).containsKey("com.example.demo.Overloaded#foo");
        long overloadKeys = graph.keySet().stream()
                .filter(k -> k.startsWith("com.example.demo.Overloaded#foo"))
                .count();
        assertThat(overloadKeys).isEqualTo(2);
        assertThat(graph.keySet()).anySatisfy(k ->
                assertThat(k).isIn("com.example.demo.Overloaded#foo(int)",
                        "com.example.demo.Overloaded#foo(String)"));
    }

    @Test
    void shouldNotExcludeTargetNamedSourceFiles() throws IOException {
        // 文件名/目录名含 "target" 的合法源码不应被 target/ 构建输出过滤误伤
        Path srcDir = tempDir.resolve("src/main/java/com/example/demo");
        Files.createDirectories(srcDir);
        Files.writeString(srcDir.resolve("TargetService.java"), """
                package com.example.demo;

                public class TargetService {
                    public void targetMethod() {}
                }
                """);

        Map<String, CallGraphNode> graph = builder.build(tempDir).graph();
        assertThat(graph).containsKey("com.example.demo.TargetService#targetMethod");
    }

    private void createTestProject(Path root) throws IOException {
        Path srcDir = root.resolve("src/main/java/com/example/demo");
        Files.createDirectories(srcDir);

        String controllerCode = """
                package com.example.demo;

                import org.springframework.web.bind.annotation.*;

                @RestController
                @RequestMapping("/api")
                public class UserController {

                    private final UserService userService;

                    public UserController(UserService userService) {
                        this.userService = userService;
                    }

                    @GetMapping("/users/{id}")
                    public User getUser(@PathVariable String id) {
                        return userService.findById(id);
                    }
                }

                class UserService {
                    public User findById(String id) {
                        return new User();
                    }
                }

                class User {
                    private String name;
                    public String getName() { return name; }
                    public void setName(String name) { this.name = name; }
                }
                """;

        Files.writeString(srcDir.resolve("UserController.java"), controllerCode);
    }
}
