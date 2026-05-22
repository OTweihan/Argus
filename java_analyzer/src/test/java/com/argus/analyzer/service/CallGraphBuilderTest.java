package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.CallGraphNode;
import com.argus.analyzer.support.SourceFileScanner;
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
        builder = new CallGraphBuilder(new SourceFileScanner(new JavaParser(config)));
        createTestProject(tempDir);
    }

    @Test
    void shouldBuildCallGraph() {
        Map<String, CallGraphNode> graph = builder.build(tempDir);
        assertThat(graph).isNotEmpty();

        // Controller → Service 调用链
        CallGraphNode controllerNode = graph.get("com.example.demo.UserController#getUser");
        assertThat(controllerNode).isNotNull();
        // 符号解析器可解析同文件内的跨类调用
        assertThat(controllerNode.getCallees())
                .contains("com.example.demo.UserService#findById");
    }

    @Test
    void shouldIncludeServiceMethods() {
        Map<String, CallGraphNode> graph = builder.build(tempDir);

        CallGraphNode serviceNode = graph.get("com.example.demo.UserService#findById");
        assertThat(serviceNode).isNotNull();
        assertThat(serviceNode.getMethodSignature()).contains("User findById");
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

        Map<String, CallGraphNode> graph = builder.build(tempDir);
        assertThat(graph).doesNotContainKey("com.example.Generated#generatedMethod");
    }

    @Test
    void shouldHandleParseFailureGracefully() throws IOException {
        // 放一个不可解析的文件，验证不会抛异常
        Path invalidDir = tempDir.resolve("src/main/java/com/example");
        Files.createDirectories(invalidDir);
        Files.writeString(invalidDir.resolve("Broken.java"), "this is not valid java code");

        Map<String, CallGraphNode> graph = builder.build(tempDir);
        // 可解析的文件仍然正常
        assertThat(graph).isNotEmpty();
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
