package com.argus.analyzer.env.classpath.parser;

import com.argus.analyzer.env.ClasspathResult;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Parses a classpath text file into a {@link ClasspathResult}.
 * Handles both Windows ({@code ;}) and Unix ({@code :}) separators,
 * and verifies each JAR path exists on disk.
 *
 * <p>Stateless utility — not a Spring bean.
 */
public final class ClasspathFileReader {

    /** Windows 盘符前缀（内容开头处的 {@code X:\} 或 {@code X:/}）。 */
    private static final Pattern DRIVE_PREFIX = Pattern.compile("^[A-Za-z]:[\\\\/]");

    public ClasspathResult read(Path classpathFile, String source) {
        try {
            String content = Files.readString(classpathFile, StandardCharsets.UTF_8).trim();
            if (content.isEmpty()) {
                return new ClasspathResult(false, false, true, List.of(), source,
                        List.of("Classpath file is empty: " + classpathFile),
                        List.of(), null, null);
            }

            // 分隔符判定（盘符感知）：
            // - 含 ';' → Windows 风格（File.pathSeparator=';'），多条目按 ';' 切分；
            // - 不含 ';' 但以盘符开头（如 C:\...）→ Windows 单条目（Windows 多条目
            //   必以 ';' 分隔），整行作为单个 JAR 路径——否则会把盘符冒号误当
            //   分隔符劈成 "C" + "\..."，导致路径损坏或全部判无效而静默降级；
            // - 其余 → Unix 风格，按 ':' 切分。
            String[] parts;
            if (!content.contains(";") && DRIVE_PREFIX.matcher(content).find()) {
                parts = new String[] {content};
            } else {
                String separator = content.contains(";") ? ";" : ":";
                parts = content.split(separator);
            }
            List<String> validJars = new ArrayList<>();
            List<String> warnings = new ArrayList<>();

            for (String part : parts) {
                String jarPath = part.trim();
                if (jarPath.isEmpty()) {
                    continue;
                }
                if (Files.exists(Paths.get(jarPath))) {
                    validJars.add(jarPath);
                } else {
                    warnings.add("JAR not found, skipping: " + jarPath);
                }
            }

            return new ClasspathResult(true, false, false, validJars, source,
                    warnings, List.of(), null, null);

        } catch (IOException e) {
            return new ClasspathResult(false, false, true, List.of(), source,
                    List.of("Failed to read classpath file: " + e.getMessage()),
                    List.of(e.getMessage()), null, null);
        }
    }
}
