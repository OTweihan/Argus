package com.argus.analyzer.env.classpath.cache;

import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModuleIndex;
import com.argus.analyzer.support.Digests;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Objects;

/**
 * Manages classpath cache metadata — file naming, hash computation,
 * validity checking, and persistence.
 */
@Component
public class ClasspathCacheManager {

    /**
     * Cache metadata for validating whether a cached classpath is still fresh.
     */
    private record CacheMetadata(String pomHash, String settingsHash, String jdkVersion, String createdAt) {
        boolean isValid(String currentPomHash, String currentSettingsHash, String currentJdkVersion) {
            return pomHash.equals(currentPomHash)
                    && Objects.equals(settingsHash, currentSettingsHash)
                    && jdkVersion.equals(currentJdkVersion);
        }

        static CacheMetadata read(Path metaFile) {
            try {
                String content = Files.readString(metaFile, StandardCharsets.UTF_8).trim();
                String pomHash = "";
                String settingsHash = "";
                String jdkVersion = "";
                String createdAt = "";
                for (String line : content.split("\n")) {
                    line = line.trim();
                    if (line.startsWith("pomHash=")) {
                        pomHash = line.substring(8);
                    } else if (line.startsWith("settingsHash=")) {
                        settingsHash = line.substring(13);
                    } else if (line.startsWith("jdkVersion=")) {
                        jdkVersion = line.substring(11);
                    } else if (line.startsWith("createdAt=")) {
                        createdAt = line.substring(10);
                    }
                }
                return new CacheMetadata(pomHash, settingsHash, jdkVersion, createdAt);
            } catch (IOException e) {
                return null;
            }
        }

        void write(Path metaFile) {
            try {
                String content = String.format(
                        "pomHash=%s\nsettingsHash=%s\njdkVersion=%s\ncreatedAt=%s\n",
                        pomHash, settingsHash, jdkVersion, createdAt);
                Files.writeString(metaFile, content, StandardCharsets.UTF_8);
            } catch (IOException e) {
                // Non-fatal; cache will be regenerated next time
            }
        }
    }

    public ClasspathCacheManager() {
    }

    /**
     * Converts a module key (e.g. {@code sub/module}) to a filesystem-safe cache file name.
     */
    public String toCacheFileName(String moduleKey) {
        return moduleKey.replace('\\', '/')
                .replaceAll("^\\./", "")
                .replace("/", "__")
                .replace(':', '_') + ".txt";
    }

    public String toMetaFileName(String moduleKey) {
        return toCacheFileName(moduleKey).replace(".txt", ".meta");
    }

    public boolean isCacheValid(Path metaFile, MavenModuleIndex moduleIndex, MavenConfig config) {
        if (!Files.exists(metaFile)) {
            return false;
        }
        CacheMetadata meta = CacheMetadata.read(metaFile);
        if (meta == null) {
            return false;
        }

        String currentPomHash = computePomHash(moduleIndex.getRootPom());
        String currentSettingsHash = computeSettingsHash(config.getSettingsXml());
        String currentJdk = getJdkVersion();

        return meta.isValid(currentPomHash, currentSettingsHash, currentJdk);
    }

    public void saveCacheMetadata(Path metaFile, MavenModuleIndex moduleIndex, MavenConfig config) {
        String pomHash = computePomHash(moduleIndex.getRootPom());
        String settingsHash = computeSettingsHash(config.getSettingsXml());
        String jdkVersion = getJdkVersion();
        String createdAt = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        new CacheMetadata(pomHash, settingsHash, jdkVersion, createdAt).write(metaFile);
    }

    // ── legacy 单模块缓存（.argus/classpath.txt）────────────────────────

    /**
     * 校验 legacy classpath 缓存元数据是否仍然新鲜。
     *
     * <p>与模块感知路径共用 {@link CacheMetadata} 口径（根 pom hash +
     * settings hash + JDK 版本）；legacy 路径没有 {@link MavenModuleIndex}，
     * 根 pom 取 {@code sourcePath/pom.xml}（非 Maven 项目视为空 hash，与
     * 「pom 不存在时不参与校验」语义一致）。</p>
     */
    public boolean isLegacyCacheValid(Path metaFile, Path sourcePath, MavenConfig config) {
        CacheMetadata meta = CacheMetadata.read(metaFile);
        if (meta == null) {
            return false;
        }
        return meta.isValid(
                computePomHash(legacyRootPom(sourcePath)),
                computeSettingsHash(config.getSettingsXml()),
                getJdkVersion());
    }

    /** 在成功重新生成 legacy 缓存后写入/刷新元数据。 */
    public void saveLegacyCacheMetadata(Path metaFile, Path sourcePath, MavenConfig config) {
        String createdAt = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        new CacheMetadata(
                computePomHash(legacyRootPom(sourcePath)),
                computeSettingsHash(config.getSettingsXml()),
                getJdkVersion(),
                createdAt).write(metaFile);
    }

    private static Path legacyRootPom(Path sourcePath) {
        if (sourcePath == null) {
            return null;
        }
        Path pom = sourcePath.resolve("pom.xml");
        return Files.exists(pom) ? pom : null;
    }

    private String computePomHash(Path rootPom) {
        if (rootPom == null || !Files.exists(rootPom)) {
            return "";
        }
        try {
            return Digests.sha256Hex(Files.readAllBytes(rootPom));
        } catch (IOException e) {
            return "";
        }
    }

    private String computeSettingsHash(String settingsXmlPath) {
        if (settingsXmlPath == null || settingsXmlPath.isEmpty()) {
            return "";
        }
        Path settingsFile = java.nio.file.Paths.get(settingsXmlPath);
        if (!Files.exists(settingsFile)) {
            return "";
        }
        try {
            return Digests.sha256Hex(Files.readAllBytes(settingsFile));
        } catch (IOException e) {
            return "";
        }
    }

    private String getJdkVersion() {
        return System.getProperty("java.version", "unknown");
    }
}
