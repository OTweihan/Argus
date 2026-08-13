package com.argus.analyzer.env;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * J2：MavenConfig 指纹统一。此前 ProjectIndexCache（缓存键）对 settingsXml 做内容
 * SHA-256，而 AnalysisJobService（幂等指纹）只存路径字符串，导致同一 clientRequestId
 * 但 settings.xml 内容不同的请求被判「同请求」却产生不同缓存键。此处收敛为单一实现，
 * settingsXml 一律按内容哈希。本测试固定该语义，防止再次分叉。
 */
class MavenConfigFingerprintTest {

    @TempDir
    Path tempDir;

    private MavenConfig configWithSettings(Path settings) {
        MavenConfig config = new MavenConfig();
        config.setSettingsXml(settings == null ? null : settings.toString());
        return config;
    }

    @Test
    void settingsXmlContentChangesFingerprint() throws IOException {
        Path s1 = tempDir.resolve("s1.xml");
        Path s2 = tempDir.resolve("s2.xml");
        Files.writeString(s1, "<settings/>");
        Files.writeString(s2, "<settings><mirror>m</mirror></settings>");

        assertThat(MavenConfigFingerprint.fingerprint(configWithSettings(s1)))
                .isNotEqualTo(MavenConfigFingerprint.fingerprint(configWithSettings(s2)));
    }

    @Test
    void nullAndBlankSettingsXmlAreNormalized() {
        MavenConfig blank = configWithSettings(null);
        MavenConfig empty = new MavenConfig();
        empty.setSettingsXml("");
        MavenConfig none = new MavenConfig();

        assertThat(MavenConfigFingerprint.fingerprint(blank))
                .isEqualTo(MavenConfigFingerprint.fingerprint(empty));
        assertThat(MavenConfigFingerprint.fingerprint(empty))
                .isEqualTo(MavenConfigFingerprint.fingerprint(none));
    }

    @Test
    void sameContentProducesStableFingerprintAcrossCalls() throws IOException {
        Path s = tempDir.resolve("s.xml");
        Files.writeString(s, "<settings><localRepository>/tmp/repo</localRepository></settings>");

        MavenConfig config = configWithSettings(s);
        // 第二次调用命中 (mtime, size) 缓存，指纹必须与首次一致。
        assertThat(MavenConfigFingerprint.fingerprint(config))
                .isEqualTo(MavenConfigFingerprint.fingerprint(config));
    }

    @Test
    void missingSettingsFileIsDistinctFromBlank() throws IOException {
        Path missing = tempDir.resolve("does-not-exist.xml");
        MavenConfig config = configWithSettings(missing);

        assertThat(MavenConfigFingerprint.fingerprint(config))
                .isNotEqualTo(MavenConfigFingerprint.fingerprint(new MavenConfig()));
    }
}
