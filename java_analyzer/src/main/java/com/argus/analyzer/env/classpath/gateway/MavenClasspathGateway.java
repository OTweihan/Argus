package com.argus.analyzer.env.classpath.gateway;

import com.argus.analyzer.env.ClasspathException;
import com.argus.analyzer.env.ClasspathGenerationException;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.classpath.maven.MavenDetector;
import com.argus.analyzer.env.classpath.maven.MavenExecutor;
import com.argus.analyzer.env.classpath.parser.ClasspathFileReader;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.List;

/**
 * Maven implementation of {@link ClasspathGateway}.
 * Adapter layer between resolvers and low-level Maven components.
 * Converts typed {@link ClasspathException}s back to {@link ClasspathResult}
 * so that upstream resolvers remain decoupled from the exception hierarchy.
 */
@Component
public class MavenClasspathGateway implements ClasspathGateway {

    private static final Logger log = LoggerFactory.getLogger(MavenClasspathGateway.class);

    private final MavenDetector mavenDetector;
    private final MavenExecutor mavenExecutor;
    private final ClasspathFileReader fileReader = new ClasspathFileReader();

    public MavenClasspathGateway(MavenDetector mavenDetector, MavenExecutor mavenExecutor) {
        this.mavenDetector = mavenDetector;
        this.mavenExecutor = mavenExecutor;
    }

    @Override
    public String detectMavenExecutable(Path sourcePath, MavenConfig config) {
        return mavenDetector.detect(sourcePath, config);
    }

    @Override
    public ClasspathResult generateClasspath(Path sourcePath, String mvnExec, MavenConfig config,
                                              long timeoutSeconds, AnalysisProgressListener progress) {
        try {
            return mavenExecutor.generateClasspath(sourcePath, mvnExec, config, timeoutSeconds, progress);
        } catch (ClasspathException e) {
            logException(e);
            return toClasspathResult(e);
        }
    }

    @Override
    public ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                       MavenConfig config, long timeout, String targetModule,
                                                       AnalysisProgressListener progress) {
        try {
            return mavenExecutor.generateClasspathForModule(workDir, outputFile, mvnExec, config,
                                                             timeout, targetModule, progress);
        } catch (ClasspathException e) {
            logException(e);
            return toClasspathResult(e);
        }
    }

    @Override
    public boolean runMvnInstall(Path workDir, String mvnExec, long timeout, AnalysisProgressListener progress) {
        return mavenExecutor.runMvnInstall(workDir, mvnExec, timeout, progress);
    }

    @Override
    public ClasspathResult readClasspathFile(Path file, String source) {
        return fileReader.read(file, source);
    }

    private void logException(ClasspathException e) {
        if (e.timedOut()) {
            log.warn("Classpath generation timed out: {}", e.getMessage());
        } else if (e instanceof ClasspathGenerationException && e.getCause() != null) {
            log.error("Classpath generation failed: {}", e.getMessage(), e);
        } else {
            log.warn("Classpath generation failed: {}", e.getMessage(), e);
        }
    }

    private ClasspathResult toClasspathResult(ClasspathException e) {
        String message = e.getMessage() != null ? e.getMessage() : "Unknown classpath error";
        ClasspathResult result = new ClasspathResult(
                false, false, true, List.of(), "none",
                List.of(message), List.of(message),
                e.commandLine(), e.exitCode()
        );
        if (e.durationMs() >= 0) {
            result.setDurationMs(e.durationMs());
        }
        result.setStdoutTail(e.stdoutTail());
        result.setStderrTail(e.stderrTail());
        result.setTimedOut(e.timedOut());
        return result;
    }
}
