package com.argus.analyzer.env.classpath.resolver;

import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModule;
import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.env.classpath.cache.ClasspathCacheManager;
import com.argus.analyzer.env.classpath.gateway.ClasspathGateway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * J-M1：单次 resolve 内对 Maven 可执行文件检测做 memo —— N 个目标模块共享同一
 * projectRoot 时，``mvn --version`` 子进程只 spawn 一次（此前每个模块都重新检测）。
 */
@ExtendWith(MockitoExtension.class)
class ModuleClasspathResolverTest {

    @TempDir
    Path tempDir;

    @Mock
    private ClasspathGateway gateway;

    @Mock
    private ClasspathCacheManager cacheManager;

    @Mock
    private MavenModuleIndex moduleIndex;

    @Mock
    private MavenModule module1;

    @Mock
    private MavenModule module2;

    private ModuleClasspathResolver resolver;

    @BeforeEach
    void setUp() {
        resolver = new ModuleClasspathResolver(gateway, cacheManager);
    }

    @Test
    void detectMavenExecutableInvokedOnceAcrossModules() throws IOException {
        Path root = Files.createTempDirectory(tempDir, "proj");
        when(moduleIndex.getBasedir()).thenReturn(root);
        when(moduleIndex.findModule("m1")).thenReturn(Optional.of(module1));
        when(moduleIndex.findModule("m2")).thenReturn(Optional.of(module2));
        when(module1.getDisplayName()).thenReturn("m1");
        when(module2.getDisplayName()).thenReturn("m2");
        when(gateway.detectMavenExecutable(any(Path.class), any(MavenConfig.class))).thenReturn("mvn");

        ClasspathResult valid = new ClasspathResult();
        valid.setAvailable(true);
        valid.setJars(List.of("a.jar"));
        when(gateway.generateClasspathForModule(
                any(Path.class), any(Path.class), anyString(), any(MavenConfig.class),
                anyLong(), any())).thenReturn(valid);

        ClasspathResult result = resolver.resolve(moduleIndex, List.of("m1", "m2"), new MavenConfig());

        assertThat(result.isAvailable()).isTrue();
        // 两个模块共用同一根目录：Maven 可执行文件只检测一次
        verify(gateway, times(1)).detectMavenExecutable(any(Path.class), any(MavenConfig.class));
    }

    @Test
    void cacheHitModulesDoNotTriggerDetection() throws IOException {
        Path root = Files.createTempDirectory(tempDir, "proj-cache");
        when(moduleIndex.getBasedir()).thenReturn(root);
        when(moduleIndex.findModule("m1")).thenReturn(Optional.of(module1));
        when(module1.getDisplayName()).thenReturn("m1");
        when(cacheManager.toCacheFileName("m1")).thenReturn("m1.txt");
        when(cacheManager.toMetaFileName("m1")).thenReturn("m1.meta");

        // 在磁盘上放置按模块缓存文件，命中有效缓存 → 无需检测 Maven 可执行文件
        Path cacheFile = root.resolve(".argus/classpath").resolve("m1.txt");
        Files.createDirectories(cacheFile.getParent());
        Files.writeString(cacheFile, "ignored");

        ClasspathResult cached = new ClasspathResult();
        cached.setAvailable(true);
        cached.setJars(List.of("cached.jar"));
        when(gateway.readClasspathFile(any(Path.class), anyString())).thenReturn(cached);
        when(cacheManager.isCacheValid(any(Path.class), any(MavenModuleIndex.class), any(MavenConfig.class)))
                .thenReturn(true);

        ClasspathResult result = resolver.resolve(moduleIndex, List.of("m1"), new MavenConfig());

        assertThat(result.isAvailable()).isTrue();
        verify(gateway, never()).detectMavenExecutable(any(Path.class), any(MavenConfig.class));
    }
}
