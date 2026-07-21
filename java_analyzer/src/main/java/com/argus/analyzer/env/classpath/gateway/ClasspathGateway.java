package com.argus.analyzer.env.classpath.gateway;

import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.service.AnalysisProgressListener;

import java.nio.file.Path;

/**
 * Abstraction over classpath generation backends (Maven, Gradle, Bazel).
 */
public interface ClasspathGateway {

    String detectMavenExecutable(Path sourcePath, MavenConfig config);

    ClasspathResult generateClasspath(Path sourcePath, String mvnExec, MavenConfig config,
                                       long timeoutSeconds, AnalysisProgressListener progress);

    ClasspathResult generateClasspathForModule(Path workDir, Path outputFile, String mvnExec,
                                                MavenConfig config, long timeout, String targetModule,
                                                AnalysisProgressListener progress);

    boolean runMvnInstall(Path workDir, String mvnExec, long timeout, AnalysisProgressListener progress);

    ClasspathResult readClasspathFile(Path file, String source);
}
