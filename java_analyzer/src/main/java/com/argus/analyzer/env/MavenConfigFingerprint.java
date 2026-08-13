package com.argus.analyzer.env;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Collections;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/**
 * Maven 配置的规范化指纹 — 缓存键（{@code ProjectIndexCache}）与幂等指纹
 * （{@code AnalysisJobService}）共用。
 *
 * <p>两处此前各自手写一份 {@link MavenConfig} 字段指纹，且语义已分叉：缓存键对
 * settingsXml 做内容 SHA-256（13 个分量），幂等指纹只存 settingsXml 路径字符串
 * （12 个分量）。后果是同一 clientRequestId 但 settings.xml 内容不同的两次请求，
 * 幂等判定为「同请求」（不抛冲突）却产生不同缓存键——两套身份判定互相矛盾。</p>
 *
 * <p>此处收敛为单一实现：settingsXml 一律按内容哈希（内容变化即身份变化），
 * classpathMode 用枚举名、空值统一归一化为 {@code ""}，保证两套判定一致。</p>
 */
public final class MavenConfigFingerprint {

    private static final String FIELD_SEPARATOR = "";

    // settings.xml 内容指纹按 (mtime, size) 键控缓存：createKey 每次都会触发
    // mavenSignature，若对同一 settings 文件反复 SHA-256 属纯重复 I/O。access-order
    // LRU + 容量上限，避免极端多项目（各自 settings.xml 路径）场景下无界增长。
    private record CachedSettings(String fingerprint, long mtime, long size) {}

    private static final int MAX_SETTINGS_CACHE = 64;

    private static final Map<String, CachedSettings> SETTINGS_CACHE = Collections.synchronizedMap(
            new LinkedHashMap<>(16, 0.75f, true) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, CachedSettings> eldest) {
                    return size() > MAX_SETTINGS_CACHE;
                }
            });

    private MavenConfigFingerprint() {}

    public static String fingerprint(MavenConfig config) {
        MavenConfig resolved = config != null ? config : new MavenConfig();
        return String.join(FIELD_SEPARATOR,
                Boolean.toString(resolved.isAutoDetect()),
                Boolean.toString(resolved.isGenerateClasspath()),
                Objects.toString(resolved.getClasspathFile(), ""),
                Objects.toString(resolved.getExecutable(), ""),
                Objects.toString(resolved.getSettingsXml(), ""),
                settingsFingerprint(resolved.getSettingsXml()),
                Objects.toString(resolved.getLocalRepository(), ""),
                Boolean.toString(resolved.isOffline()),
                Objects.toString(resolved.getDependencyPluginVersion(), ""),
                Long.toString(resolved.getOfflineTimeoutSeconds()),
                Long.toString(resolved.getOnlineTimeoutSeconds()),
                Objects.toString(resolved.getClasspathMode(), ""),
                Boolean.toString(resolved.isPrepareReactorArtifacts())
        );
    }

    private static String settingsFingerprint(String rawPath) {
        if (rawPath == null || rawPath.isBlank()) return "";
        Path path = Path.of(rawPath).toAbsolutePath().normalize();
        if (!Files.isRegularFile(path)) {
            SETTINGS_CACHE.remove(path.toString());
            return "missing";
        }
        try {
            long mtime = Files.getLastModifiedTime(path).toMillis();
            long size = Files.size(path);
            CachedSettings cached = SETTINGS_CACHE.get(path.toString());
            if (cached != null && cached.mtime() == mtime && cached.size() == size) {
                return cached.fingerprint();
            }
            String fingerprint = computeSha256(path);
            SETTINGS_CACHE.put(path.toString(), new CachedSettings(fingerprint, mtime, size));
            return fingerprint;
        } catch (IOException error) {
            throw new IllegalStateException("Failed to fingerprint Maven settings: " + path, error);
        }
    }

    private static String computeSha256(Path path) throws IOException {
        MessageDigest digest = newDigest();
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                digest.update(buffer, 0, read);
            }
            return HexFormat.of().formatHex(digest.digest());
        }
    }

    private static MessageDigest newDigest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }
}
