package com.argus.analyzer.support;

import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.jar.Attributes;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;
import java.util.zip.ZipEntry;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JarTypeSolverPoolTest {

    @TempDir
    Path tempDir;

    private Path createJar(String name) throws IOException {
        Manifest manifest = new Manifest();
        manifest.getMainAttributes().put(Attributes.Name.MANIFEST_VERSION, "1.0");
        Path path = tempDir.resolve(name);
        try (JarOutputStream out = new JarOutputStream(Files.newOutputStream(path), manifest)) {
            out.putNextEntry(new ZipEntry("com/example/Dummy.class"));
            out.write(new byte[] {1, 2, 3});
            out.closeEntry();
        }
        return path;
    }

    @Test
    void shouldReuseSolverForSameJarAndCountHits() throws IOException {
        JarTypeSolverPool pool = new JarTypeSolverPool(8);
        Path jar = createJar("a.jar");

        JarTypeSolver first = pool.acquire(jar);
        JarTypeSolver second = pool.acquire(jar);

        assertThat(second).isSameAs(first);
        assertThat(pool.pooledCount()).isEqualTo(1);

        JarTypeSolverPool.PoolStats stats = pool.stats();
        assertThat(stats.acquisitions()).isEqualTo(2);
        assertThat(stats.hits()).isEqualTo(1);
        assertThat(stats.opens()).isEqualTo(1);
        assertThat(stats.evictions()).isZero();
    }

    @Test
    void shouldEvictLeastRecentlyUsedBeyondCapacity() throws IOException {
        JarTypeSolverPool pool = new JarTypeSolverPool(1);
        Path jarA = createJar("a.jar");
        Path jarB = createJar("b.jar");

        JarTypeSolver solverA = pool.acquire(jarA);
        assertThat(pool.pooledCount()).isEqualTo(1);

        // 容量 1：放入 B 时淘汰 A（句柄在淘汰时关闭，不累积）
        pool.acquire(jarB);
        assertThat(pool.pooledCount()).isEqualTo(1);
        assertThat(pool.stats().evictions()).isEqualTo(1);

        // 被淘汰的条目可重新打开为新实例，计数同步递增
        assertThat(pool.acquire(jarA)).isNotSameAs(solverA);
        assertThat(pool.stats().opens()).isEqualTo(3);
        assertThat(pool.stats().acquisitions()).isEqualTo(3);
    }

    @Test
    void shouldRejectNonPositiveCapacity() {
        assertThatThrownBy(() -> new JarTypeSolverPool(0))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
