package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.ClasspathGenerationException;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenExecutionException;
import com.argus.analyzer.env.MavenTimeoutException;
import com.argus.analyzer.env.classpath.parser.ClasspathFileReader;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Maven process execution abstraction.
 * Handles {@link ProcessBuilder} management, timeout control,
 * stdout/stderr consumption, and classpath file generation.
 */
@Component
public class MavenExecutor {

    private static final Logger log = LoggerFactory.getLogger(MavenExecutor.class);
    private static final int MAVEN_OUTPUT_TAIL_CHARS = 4000;

    private final ClasspathFileReader fileReader = new ClasspathFileReader();
    private final ExecutorService streamExecutor;

    public MavenExecutor(@Qualifier("mavenStreamExecutor") ExecutorService streamExecutor) {
        this.streamExecutor = streamExecutor;
    }

    /**
     * Legacy single-module classpath generation (no target module selector).
     */
    public ClasspathResult generateClasspath(Path sourcePath, String mvnExec, MavenConfig config,
                                              long timeoutSeconds) {
        return generateClasspath(sourcePath, mvnExec, config, timeoutSeconds, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult generateClasspath(Path sourcePath, String mvnExec, MavenConfig config,
                                              long timeoutSeconds, AnalysisProgressListener progress) {
        Path outputDir = sourcePath.resolve(".argus");
        try {
            Files.createDirectories(outputDir);
        } catch (IOException e) {
            throw new ClasspathGenerationException(
                    "Failed to create .argus directory: " + e.getMessage(), e);
        }
        Path outputFile = outputDir.resolve("classpath.txt");
        return generateClasspathForModule(sourcePath, outputFile, mvnExec, config, timeoutSeconds, null, progress);
    }

    /**
     * Generates classpath for a specific module via {@code maven-dependency-plugin:build-classpath}.
     */
    public ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                       MavenConfig config, long timeoutSeconds, String targetModule) {
        return generateClasspathForModule(workDir, outputFile, mvnExec, config, timeoutSeconds, targetModule,
                AnalysisProgressListener.NOOP);
    }

    public ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                       MavenConfig config, long timeoutSeconds, String targetModule,
                                                       AnalysisProgressListener progress) {
        List<String> cmd = new ArrayList<>();
        cmd.add(mvnExec);

        if (targetModule != null && !targetModule.isEmpty()) {
            cmd.add("-pl");
            cmd.add(targetModule);
            cmd.add("-am");
        }
        cmd.add("org.apache.maven.plugins:maven-dependency-plugin:" + config.getDependencyPluginVersion() + ":build-classpath");

        cmd.add("-Dmdep.outputFile=" + outputFile.toAbsolutePath());
        cmd.add("-DincludeScope=compile");

        if (config.getSettingsXml() != null && !config.getSettingsXml().isEmpty()) {
            cmd.add("-s");
            cmd.add(config.getSettingsXml());
        }
        if (config.getLocalRepository() != null && !config.getLocalRepository().isEmpty()) {
            cmd.add("-Dmaven.repo.local=" + config.getLocalRepository());
        }
        if (config.isOffline()) {
            cmd.add("-o");
        }

        return executeMaven(workDir, outputFile, mvnExec, config, cmd, timeoutSeconds, progress);
    }

    /**
     * Runs {@code mvn install -DskipTests -q -o} to prepare reactor artifacts.
     */
    public boolean runMvnInstall(Path workDir, String mvnExec, long timeoutSeconds,
                                  AnalysisProgressListener progress) {
        List<String> cmd = new ArrayList<>();
        cmd.add(mvnExec);
        cmd.add("install");
        cmd.add("-DskipTests");
        cmd.add("-q");
        cmd.add("-o");

        log.info("[CLASSPATH] Preparing reactor: {}", String.join(" ", cmd));
        progress.onEvent("classpath", "INFO", "Preparing reactor artifacts: mvn install -DskipTests");

        try {
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.directory(workDir.toFile());
            pb.redirectErrorStream(true);
            Process process = pb.start();

            StringBuilder outputCapture = new StringBuilder();
            Thread outputReader = new Thread(() -> {
                try (var reader = new BufferedReader(
                        new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (outputCapture.length() < MAVEN_OUTPUT_TAIL_CHARS * 2) {
                            outputCapture.append(line).append("\n");
                        }
                    }
                } catch (IOException ignored) {
                    // Normal — pipe closes when process exits
                }
            }, "mvn-install-reader");
            outputReader.setDaemon(true);
            outputReader.start();

            boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                outputReader.interrupt();
                log.warn("[CLASSPATH] Reactor install timed out after {}s", timeoutSeconds);
                return false;
            }
            try { outputReader.join(1000); } catch (InterruptedException ignored) {}

            int exitCode = process.exitValue();
            if (exitCode != 0) {
                String tail = outputCapture.toString();
                if (tail.length() > MAVEN_OUTPUT_TAIL_CHARS) {
                    tail = tail.substring(tail.length() - MAVEN_OUTPUT_TAIL_CHARS);
                }
                log.warn("[CLASSPATH] Reactor install failed with exit code {}; tail: {}",
                        exitCode, tail);
                return false;
            }
            log.info("[CLASSPATH] Reactor install completed successfully");
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("[CLASSPATH] Reactor install interrupted: {}", e.getMessage());
            return false;
        } catch (IOException e) {
            log.warn("[CLASSPATH] Reactor install failed: {}", e.getMessage());
            return false;
        }
    }

    private ClasspathResult executeMaven(Path workDir, Path outputFile, String mvnExec,
                                          MavenConfig config, List<String> cmd, long timeoutSeconds,
                                          AnalysisProgressListener progress) {
        String commandLine = String.join(" ", cmd);
        log.info("[CLASSPATH] Executing: {}", commandLine);
        progress.onEvent("classpath", "INFO", "Executing Maven classpath command: " + commandLine);

        long started = System.nanoTime();
        long durationMs = -1;
        try {
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.directory(workDir.toFile());
            pb.redirectErrorStream(false);

            Process process = pb.start();
            CompletableFuture<String> stdoutFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getInputStream(), "stdout", progress), streamExecutor);
            CompletableFuture<String> stderrFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getErrorStream(), "stderr", progress), streamExecutor);
            boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
            durationMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);

            if (!finished) {
                process.destroyForcibly();
                String stdout = awaitOutput(stdoutFuture);
                String stderr = awaitOutput(stderrFuture);
                progress.onEvent("classpath", "ERROR", "Maven classpath generation timed out after "
                        + timeoutSeconds + "s");
                throw new MavenTimeoutException(
                        "Maven classpath generation timed out after " + timeoutSeconds + "s",
                        timeoutSeconds, commandLine, durationMs, tail(stdout), tail(stderr));
            }

            int exitCode = process.exitValue();
            String stdout = awaitOutput(stdoutFuture);
            String stderr = awaitOutput(stderrFuture);
            if (exitCode != 0) {
                progress.onEvent("classpath", "ERROR", "Maven exited with code " + exitCode);
                throw new MavenExecutionException(
                        "Maven exited with code " + exitCode + ": " + tail(stderr),
                        exitCode, commandLine, tail(stderr), durationMs, tail(stdout));
            }

            if (!Files.exists(outputFile)) {
                throw new ClasspathGenerationException(
                        "Maven completed but classpath file was not created",
                        commandLine, exitCode, durationMs, tail(stdout), tail(stderr));
            }

            String mode = config.isOffline() ? "offline-" : "online-";
            String wrapper = mvnExec.endsWith("mvnw.cmd") || mvnExec.endsWith("mvnw") ? "wrapper" : "system";
            ClasspathResult result = fileReader.read(outputFile, "maven-" + mode + wrapper);
            result.setGenerated(true);
            result.setCommand(commandLine);
            result.setExitCode(exitCode);
            result.setDurationMs(durationMs);
            result.setStdoutTail(tail(stdout));
            result.setStderrTail(tail(stderr));
            log.info("[CLASSPATH] Classpath generated: {} jars in {}ms", result.getJars().size(), durationMs);
            progress.onEvent("classpath", "INFO", "Classpath generated: " + result.getJars().size()
                    + " jars in " + durationMs + "ms");
            return result;

        } catch (IOException e) {
            throw new ClasspathGenerationException("Maven execution failed: " + e.getMessage(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ClasspathGenerationException("Maven execution interrupted", e);
        }
    }

    private String readStream(InputStream stream) {
        return readStream(stream, null, AnalysisProgressListener.NOOP);
    }

    private String readStream(InputStream stream, String streamName, AnalysisProgressListener progress) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                if (!sb.isEmpty()) {
                    sb.append("\n");
                }
                sb.append(line);
                if (streamName != null && shouldLogMavenLine(line)) {
                    log.info("[CLASSPATH][MAVEN {}] {}", streamName, line);
                    progress.onEvent("classpath", "INFO", streamName + ": " + line);
                }
            }
            return sb.toString();
        } catch (IOException e) {
            return "(failed to read stream: " + e.getMessage() + ")";
        }
    }

    private String awaitOutput(CompletableFuture<String> outputFuture) {
        try {
            return outputFuture.get(5, TimeUnit.SECONDS);
        } catch (Exception e) {
            return "(failed to collect Maven output: " + e.getMessage() + ")";
        }
    }

    private String tail(String value) {
        if (value == null || value.length() <= MAVEN_OUTPUT_TAIL_CHARS) {
            return value;
        }
        return value.substring(value.length() - MAVEN_OUTPUT_TAIL_CHARS);
    }

    private boolean shouldLogMavenLine(String line) {
        if (line == null || line.isBlank()) {
            return false;
        }
        return line.contains("[ERROR]")
                || line.contains("[WARNING]")
                || line.contains("[INFO] Building")
                || line.contains("[INFO] Reactor")
                || line.contains("[INFO] BUILD")
                || line.contains("Downloading")
                || line.contains("Downloaded");
    }
}
