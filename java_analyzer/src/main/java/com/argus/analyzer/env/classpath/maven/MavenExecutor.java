package com.argus.analyzer.env.classpath.maven;

import com.argus.analyzer.env.ClasspathGenerationException;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenExecutionException;
import com.argus.analyzer.env.MavenTimeoutException;
import com.argus.analyzer.env.classpath.parser.ClasspathFileReader;
import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.domain.JobCancelledException;
import com.argus.analyzer.service.MavenProcessRegistry;
import com.argus.analyzer.support.ProcessTreeKiller;
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
 * Handles {@link ProcessBuilder} management, timeout + cooperative cancellation
 * (O-04) control, stdout/stderr consumption, and classpath file generation.
 */
@Component
public class MavenExecutor {

    private static final Logger log = LoggerFactory.getLogger(MavenExecutor.class);
    private static final int MAVEN_OUTPUT_TAIL_CHARS = 4000;
    /** 输出累积缓冲上限（保留末尾），防止大构建 OOM；远大于 tail 所需即可。 */
    private static final int MAX_OUTPUT_BUFFER_CHARS = 16_384;
    private static final long PROCESS_POLL_MILLIS = 250;

    private final ClasspathFileReader fileReader = new ClasspathFileReader();
    private final ExecutorService streamExecutor;
    private final MavenProcessRegistry processRegistry;

    public MavenExecutor(@Qualifier("mavenStreamExecutor") ExecutorService streamExecutor,
                         MavenProcessRegistry processRegistry) {
        this.streamExecutor = streamExecutor;
        this.processRegistry = processRegistry;
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
     * Cancellation (O-04) kills the process tree and propagates
     * {@link JobCancelledException} instead of degrading silently.
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
            processRegistry.register(progress, process);

            // 与 executeMaven 同口径：streamExecutor + readStream 有界滑动窗口，
            // 失败诊断取到的是真实输出的末尾（构建报错几乎都在末尾）。
            // 此前是裸线程 + 「前 16000 字符截断后取尾」，拿到的是输出中段切片。
            CompletableFuture<String> outputFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getInputStream(), null, progress), streamExecutor);

            ProcessOutcome outcome = waitForProcess(process, timeoutSeconds, progress);
            if (outcome == ProcessOutcome.CANCELLED) {
                throw new JobCancelledException("Maven reactor install cancelled");
            }
            if (outcome == ProcessOutcome.TIMED_OUT) {
                log.warn("[CLASSPATH] Reactor install timed out after {}s", timeoutSeconds);
                return false;
            }

            int exitCode = process.exitValue();
            String tail = tail(awaitOutput(outputFuture));
            if (exitCode != 0) {
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
            processRegistry.register(progress, process);
            CompletableFuture<String> stdoutFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getInputStream(), "stdout", progress), streamExecutor);
            CompletableFuture<String> stderrFuture = CompletableFuture.supplyAsync(
                    () -> readStream(process.getErrorStream(), "stderr", progress), streamExecutor);

            ProcessOutcome outcome = waitForProcess(process, timeoutSeconds, progress);
            durationMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);

            if (outcome == ProcessOutcome.CANCELLED) {
                // 协作取消：不收集输出，直接向上传播取消信号，由 runJob 落 CANCELLED
                throw new JobCancelledException("Maven classpath generation cancelled");
            }
            if (outcome == ProcessOutcome.TIMED_OUT) {
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
            // 协作取消走 waitForProcess 的 isCancelled() 路径（JobCancelledException），
            // 此处 interrupt 保持既有失败语义（ClasspathGenerationException）。
            throw new ClasspathGenerationException("Maven execution interrupted", e);
        }
    }

    /**
     * 在进程存活期间轮询：协作取消 / 进程退出 / 整体 deadline 超时。
     * 超时与取消都会强制终止整个进程树（含后代）。
     *
     * <p>先检查取消标志再检查进程退出：``cancel()/enforceDeadlines()`` 会先置
     * 取消令牌、再由 {@link MavenProcessRegistry} 强制销毁进程——若先查
     * ``process.waitFor``，被强杀后的非零退出码会被误判为 FINISHED→MavenExecutionException
     * →FAILED，而取消应落 CANCELLED。
     */
    private static ProcessOutcome waitForProcess(Process process, long timeoutSeconds,
                                                 AnalysisProgressListener progress) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(Math.max(1, timeoutSeconds));
        while (true) {
            if (progress.isCancelled()) {
                killProcessTree(process);
                return ProcessOutcome.CANCELLED;
            }
            if (process.waitFor(PROCESS_POLL_MILLIS, TimeUnit.MILLISECONDS)) {
                return ProcessOutcome.FINISHED;
            }
            if (System.nanoTime() >= deadline) {
                killProcessTree(process);
                return ProcessOutcome.TIMED_OUT;
            }
        }
    }

    private static void killProcessTree(Process process) {
        ProcessTreeKiller.kill(process);
    }

    private enum ProcessOutcome {
        FINISHED, TIMED_OUT, CANCELLED
    }

    private String readStream(InputStream stream, String streamName, AnalysisProgressListener progress) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            // 有界缓冲：只保留末尾若干字符，避免大型构建把全量 stdout/stderr 累积进内存
            // （`tail()` 最终也只会取末尾 MAVEN_OUTPUT_TAIL_CHARS 字符，中间部分无保留价值）。
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append('\n');
                if (sb.length() > MAX_OUTPUT_BUFFER_CHARS) {
                    sb.delete(0, sb.length() - MAX_OUTPUT_BUFFER_CHARS);
                }
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
