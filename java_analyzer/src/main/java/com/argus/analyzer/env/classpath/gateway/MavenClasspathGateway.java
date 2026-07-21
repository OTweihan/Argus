package com.argus.analyzer.env.classpath.gateway;

import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.classpath.maven.MavenDetector;
import com.argus.analyzer.env.classpath.maven.MavenExecutor;
import com.argus.analyzer.env.classpath.parser.ClasspathFileReader;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.springframework.stereotype.Component;

import java.nio.file.Path;

/**
 * Maven implementation of {@link ClasspathGateway}.
 * Adapter layer between resolvers and low-level Maven components.
 */
@Component
public class MavenClasspathGateway implements ClasspathGateway {

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
        return mavenExecutor.generateClasspath(sourcePath, mvnExec, config, timeoutSeconds, progress);
    }

    @Override
    public ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                       MavenConfig config, long timeout, String targetModule,
                                                       AnalysisProgressListener progress) {
        return mavenExecutor.generateClasspathForModule(workDir, outputFile, mvnExec, config,
                                                         timeout, targetModule, progress);
    }

    @Override
    public boolean runMvnInstall(Path workDir, String mvnExec, long timeout, AnalysisProgressListener progress) {
        return mavenExecutor.runMvnInstall(workDir, mvnExec, timeout, progress);
    }

    @Override
    public ClasspathResult readClasspathFile(Path file, String source) {
        return fileReader.read(file, source);
    }
}
