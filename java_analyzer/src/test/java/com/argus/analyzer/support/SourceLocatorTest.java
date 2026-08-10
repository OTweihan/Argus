package com.argus.analyzer.support;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

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

    // ── resolveForAnalysis：allowed-source-roots 边界（fail-closed） ───────────

    @Test
    void shouldResolveWithinAllowedRoot() throws IOException {
        Path root = Files.createDirectories(tempDir.resolve("allowed"));
        SourceLocator strict = new SourceLocator(List.of(root));

        Path resolved = strict.resolveForAnalysis(root.toString());

        assertThat(resolved).isEqualTo(root.toRealPath());
    }

    @Test
    void shouldRejectPathOutsideAllowedRoots() throws IOException {
        Path root = Files.createDirectories(tempDir.resolve("allowed"));
        Path other = Files.createDirectories(tempDir.resolve("other"));
        SourceLocator strict = new SourceLocator(List.of(root));

        assertThatThrownBy(() -> strict.resolveForAnalysis(other.toString()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("outside allowed roots");
    }

    @Test
    void shouldRejectSymlinkEscape() throws IOException {
        Path root = Files.createDirectories(tempDir.resolve("allowed"));
        Path outside = Files.createDirectories(tempDir.resolve("outside"));
        Path link = root.resolve("escape");
        try {
            Files.createSymbolicLink(link, outside);
        } catch (IOException | UnsupportedOperationException | SecurityException e) {
            // Windows 无开发者模式 / Linux 受限环境可能不允许建符号链接。
            Assumptions.assumeTrue(false, "symlink not supported on this platform");
            return;
        }
        SourceLocator strict = new SourceLocator(List.of(root));

        // 符号链接逃逸：real 路径解析到 allowed root 之外 → 拒绝。
        assertThatThrownBy(() -> strict.resolveForAnalysis(link.toString()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("outside allowed roots");
    }

    @Test
    void shouldAllowSymlinkPointingInsideRoot() throws IOException {
        Path root = Files.createDirectories(tempDir.resolve("allowed"));
        Path inner = Files.createDirectories(root.resolve("inner"));
        Path link = root.resolve("inner-link");
        try {
            Files.createSymbolicLink(link, inner);
        } catch (IOException | UnsupportedOperationException | SecurityException e) {
            Assumptions.assumeTrue(false, "symlink not supported on this platform");
            return;
        }
        SourceLocator strict = new SourceLocator(List.of(root));

        assertThat(strict.resolveForAnalysis(link.toString())).isEqualTo(inner.toRealPath());
    }
}
