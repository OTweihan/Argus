package com.argus.analyzer.service;

import com.argus.analyzer.api.dto.EndpointInfo;
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

class ControllerExtractorTest {

    @TempDir
    Path tempDir;

    private ControllerExtractor extractor;

    @BeforeEach
    void setUp() throws IOException {
        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        extractor = new ControllerExtractor(new SourceFileScanner(
            new JavaParser(config),
            new SourceScannerCache(new MavenProjectLocator(), new MavenModuleScanner())
        ));
        createTestProject(tempDir);
    }

    @Test
    void shouldExtractEndpoints() {
        List<EndpointInfo> endpoints = extractor.extract(tempDir);
        assertThat(endpoints).isNotEmpty();

        EndpointInfo helloEndpoint = endpoints.stream()
                .filter(e -> e.path().equals("/api/hello"))
                .findFirst()
                .orElse(null);
        assertThat(helloEndpoint).isNotNull();
        assertThat(helloEndpoint.httpMethod()).isEqualTo("GET");
    }

    @Test
    void shouldExtractMultipleHttpMethods() {
        List<EndpointInfo> endpoints = extractor.extract(tempDir);
        assertThat(endpoints)
                .extracting(EndpointInfo::httpMethod)
                .contains("GET", "POST");
    }

    private void createTestProject(Path root) throws IOException {
        Path srcDir = root.resolve("src/main/java/com/example/demo");
        Files.createDirectories(srcDir);

        String controllerCode = """
                package com.example.demo;

                import org.springframework.web.bind.annotation.*;
                import java.util.List;

                @RestController
                @RequestMapping("/api")
                public class TestController {

                    @GetMapping("/hello")
                    public String hello() {
                        return "hello";
                    }

                    @PostMapping("/users")
                    public User createUser(@RequestBody User user) {
                        return user;
                    }

                    @GetMapping("/users/{id}")
                    public User getUser(@PathVariable String id) {
                        return new User();
                    }
                }

                class User {
                    private String name;
                    public String getName() { return name; }
                    public void setName(String name) { this.name = name; }
                }
                """;

        Files.writeString(srcDir.resolve("TestController.java"), controllerCode);
    }
}
