package com.argus.analyzer.support;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * SHA-256 摘要工具，收敛 {@code ProjectIndexCache} / {@code MavenConfigFingerprint} /
 * {@code ClasspathCacheManager} 三处重复的摘要构造与十六进制编码样板。
 */
public final class Digests {

    private static final int BUFFER_SIZE = 8192;

    private Digests() {
    }

    /** 新建 SHA-256 摘要器（SHA-256 缺省时抛 {@link IllegalStateException}）。 */
    public static MessageDigest newSha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }

    /** 字节数组的 SHA-256 十六进制摘要。 */
    public static String sha256Hex(byte[] content) {
        return HexFormat.of().formatHex(newSha256().digest(content));
    }

    /** 文件的 SHA-256 十六进制摘要（流式读取，避免整文件入内存）。 */
    public static String sha256Hex(Path path) throws IOException {
        MessageDigest digest = newSha256();
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[BUFFER_SIZE];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                digest.update(buffer, 0, read);
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }
}
