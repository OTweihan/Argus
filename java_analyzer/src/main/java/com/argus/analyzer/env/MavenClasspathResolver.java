package com.argus.analyzer.env;

import com.argus.analyzer.env.classpath.resolver.LegacyClasspathResolver;
import com.argus.analyzer.env.classpath.resolver.ModuleClasspathResolver;
import com.argus.analyzer.service.AnalysisProgressListener;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.List;

/**
 * Facade for Maven classpath resolution. All actual resolution logic is delegated
 * to {@link com.argus.analyzer.env.classpath.resolver.LegacyClasspathResolver}
 * and {@link com.argus.analyzer.env.classpath.resolver.ModuleClasspathResolver}.
 *
 * <p>This class exists solely to maintain the public API contract for callers
 * (currently only {@code ProjectAnalyzerService}). It contains no business logic.
 */
@Service
public class MavenClasspathResolver {

    private final LegacyClasspathResolver legacyResolver;
    private final ModuleClasspathResolver moduleResolver;

    public MavenClasspathResolver(LegacyClasspathResolver legacyResolver,
                                  ModuleClasspathResolver moduleResolver) {
        this.legacyResolver = legacyResolver;
        this.moduleResolver = moduleResolver;
    }

    public ClasspathResult resolve(Path sourcePath, MavenConfig config) {
        return legacyResolver.resolve(sourcePath, config, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult resolve(Path sourcePath, MavenConfig config, AnalysisProgressListener progress) {
        return legacyResolver.resolve(sourcePath, config, progress);
    }

    public ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules, MavenConfig config) {
        return moduleResolver.resolve(moduleIndex, targetModules, config, AnalysisProgressListener.NOOP);
    }

    public ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules,
                                   MavenConfig config, AnalysisProgressListener progress) {
        return moduleResolver.resolve(moduleIndex, targetModules, config, progress);
    }
}
