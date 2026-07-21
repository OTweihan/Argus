package com.argus.analyzer.env.classpath.cache;

import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModuleIndex;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HexFormat;
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

    private String computePomHash(Path rootPom) {
        if (rootPom == null || !Files.exists(rootPom)) {
            return "";
        }
        try {
            byte[] content = Files.readAllBytes(rootPom);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(content);
            return HexFormat.of().formatHex(hash);
        } catch (IOException | NoSuchAlgorithmException e) {
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
            byte[] content = Files.readAllBytes(settingsFile);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(content);
            return HexFormat.of().formatHex(hash);
        } catch (IOException | NoSuchAlgorithmException e) {
            return "";
        }
    }

    private String getJdkVersion() {
        return System.getProperty("java.version", "unknown");
    }
}
