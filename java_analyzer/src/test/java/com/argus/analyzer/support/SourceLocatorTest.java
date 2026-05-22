package com.argus.analyzer.support;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SourceLocatorTest {

    @TempDir
    Path tempDir;

    private final SourceLocator locator = new SourceLocator();

    @Test
    void shouldResolveExistingDirectory() throws IOException {
        Path resolved = locator.resolve(tempDir.toString());
        assertThat(resolved).isEqualTo(tempDir.toAbsolutePath().normalize());
    }

    @Test
    void shouldThrowForNonExistentPath() {
        String nonExistent = tempDir.resolve("nonexistent").toString();
        assertThatThrownBy(() -> locator.resolve(nonExistent))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void shouldThrowForFilePath() throws IOException {
        Path file = tempDir.resolve("test.txt");
        Files.writeString(file, "content");
        assertThatThrownBy(() -> locator.resolve(file.toString()))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
