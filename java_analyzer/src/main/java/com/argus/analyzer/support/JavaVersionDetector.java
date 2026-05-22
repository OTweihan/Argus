package com.argus.analyzer.support;

import com.github.javaparser.ParserConfiguration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 从构建文件自动检测项目的 Java 语言版本。
 */
public class JavaVersionDetector {

    private static final Logger log = LoggerFactory.getLogger(JavaVersionDetector.class);

    private static final Pattern POM_JAVA_VERSION = Pattern.compile(
            "<java\\.version>\\s*(\\d+)\\s*</java\\.version>", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern POM_COMPILER_SOURCE = Pattern.compile(
            "<maven\\.compiler\\.source>\\s*(\\d+)\\s*</maven\\.compiler\\.source>", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern POM_COMPILER_RELEASE = Pattern.compile(
            "<maven\\.compiler\\.release>\\s*(\\d+)\\s*</maven\\.compiler\\.release>", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern GRADLE_SOURCE_COMPAT = Pattern.compile(
            "sourceCompatibility\\s*=\\s*['\"]?(\\d+)", Pattern.CASE_INSENSITIVE
    );

    /**
     * 检测指定项目的 Java 语言级别。
     *
     * @param sourcePath 项目根目录
     * @return 检测到的语言级别，无法检测时返回 JAVA_17
     */
    public static ParserConfiguration.LanguageLevel detect(Path sourcePath) {
        int version = detectVersion(sourcePath);
        if (version > 0) {
            log.info("Detected Java language level: {}", version);
            return toLanguageLevel(version);
        }
        log.info("Could not detect Java version, defaulting to JAVA_17");
        return ParserConfiguration.LanguageLevel.JAVA_17;
    }

    static int detectVersion(Path sourcePath) {
        // Try pom.xml
        Path pom = sourcePath.resolve("pom.xml");
        if (Files.exists(pom)) {
            try {
                String content = Files.readString(pom);

                Matcher release = POM_COMPILER_RELEASE.matcher(content);
                if (release.find()) return Integer.parseInt(release.group(1));

                Matcher source = POM_COMPILER_SOURCE.matcher(content);
                if (source.find()) return Integer.parseInt(source.group(1));

                Matcher javaVer = POM_JAVA_VERSION.matcher(content);
                if (javaVer.find()) return Integer.parseInt(javaVer.group(1));
            } catch (IOException e) {
                log.warn("Failed to read pom.xml: {}", e.getMessage());
            }
        }

        // Try build.gradle
        Path gradle = sourcePath.resolve("build.gradle");
        if (Files.exists(gradle)) {
            try {
                String content = Files.readString(gradle);
                Matcher m = GRADLE_SOURCE_COMPAT.matcher(content);
                if (m.find()) return Integer.parseInt(m.group(1));
            } catch (IOException e) {
                log.warn("Failed to read build.gradle: {}", e.getMessage());
            }
        }

        return 0;
    }

    private static ParserConfiguration.LanguageLevel toLanguageLevel(int version) {
        return switch (version) {
            case 8 -> ParserConfiguration.LanguageLevel.JAVA_8;
            case 9 -> ParserConfiguration.LanguageLevel.JAVA_9;
            case 10 -> ParserConfiguration.LanguageLevel.JAVA_10;
            case 11 -> ParserConfiguration.LanguageLevel.JAVA_11;
            case 12 -> ParserConfiguration.LanguageLevel.JAVA_12;
            case 13 -> ParserConfiguration.LanguageLevel.JAVA_13;
            case 14 -> ParserConfiguration.LanguageLevel.JAVA_14;
            case 15 -> ParserConfiguration.LanguageLevel.JAVA_15;
            case 16 -> ParserConfiguration.LanguageLevel.JAVA_16;
            case 17 -> ParserConfiguration.LanguageLevel.JAVA_17;
            case 18 -> ParserConfiguration.LanguageLevel.JAVA_18;
            case 19 -> ParserConfiguration.LanguageLevel.JAVA_19;
            case 20 -> ParserConfiguration.LanguageLevel.JAVA_20;
            case 21 -> ParserConfiguration.LanguageLevel.JAVA_21;
            default -> ParserConfiguration.LanguageLevel.JAVA_17;
        };
    }
}
