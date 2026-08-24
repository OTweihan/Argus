package com.argus.analyzer.support;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;

/**
 * 源码树内容指纹（J5 自 {@link ProjectIndexCache} 抽出）。
 *
 * <p>对参与指纹的输入文件规则（{@link #isFingerprintInput}：.java 与
 * pom/gradle 构建文件）与规范化摘要算法集中维护；缓存类只负责计时与
 * 键组装，不感知文件选择细节。</p>
 */
public final class SourceFingerprint {

    private SourceFingerprint() {}

    /**
     * 计算源码树规范化 SHA-256 指纹：按相对路径排序，依次混入相对路径字节
     * 与文件内容字节（0 字节分隔，避免拼接歧义）。
     *
     * @throws IllegalStateException 源码树遍历/读取失败时
     */
    public static String compute(Path sourcePath) {
        MessageDigest digest = Digests.newSha256();
        List<Path> relevant = new ArrayList<>();
        try (var paths = Files.walk(sourcePath)) {
            paths.filter(Files::isRegularFile)
                    .filter(SourceFingerprint::isFingerprintInput)
                    .forEach(relevant::add);
            relevant.sort(Comparator.comparing(path -> sourcePath.relativize(path).toString()));
            byte[] buffer = new byte[8192];
            for (Path path : relevant) {
                String relative = sourcePath.relativize(path).toString().replace('\\', '/');
                digest.update(relative.getBytes(StandardCharsets.UTF_8));
                digest.update((byte) 0);
                try (InputStream input = Files.newInputStream(path)) {
                    int read;
                    while ((read = input.read(buffer)) >= 0) {
                        digest.update(buffer, 0, read);
                    }
                }
                digest.update((byte) 0);
            }
        } catch (Exception error) {
            throw new IllegalStateException("Failed to fingerprint source tree: " + sourcePath, error);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    /** 是否参与源码指纹的输入文件。新增构建文件类型时在此同步。 */
    public static boolean isFingerprintInput(Path path) {
        String name = path.getFileName().toString();
        return name.endsWith(".java")
                || name.equals("pom.xml")
                || name.equals("build.gradle")
                || name.equals("build.gradle.kts")
                || name.equals("settings.gradle")
                || name.equals("settings.gradle.kts");
    }
}
