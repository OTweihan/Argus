package com.argus.analyzer.env;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 单个 Maven 模块的元信息。
 */
public class MavenModule {

    private String groupId;
    private String artifactId;
    private String version;
    private String packaging = "jar";
    private String modulePath;
    private Path baseDir;
    private Path pomFile;
    private List<Path> sourceRoots = Collections.emptyList();
    private boolean aggregator;
    private boolean applicationModule;
    private ModuleType moduleType = ModuleType.UNKNOWN;

    public MavenModule() {}

    public String getGroupId() { return groupId; }
    public void setGroupId(String groupId) { this.groupId = groupId; }

    public String getArtifactId() { return artifactId; }
    public void setArtifactId(String artifactId) { this.artifactId = artifactId; }

    public String getVersion() { return version; }
    public void setVersion(String version) { this.version = version; }

    public String getPackaging() { return packaging; }
    public void setPackaging(String packaging) { this.packaging = packaging; }

    public String getModulePath() { return modulePath; }
    public void setModulePath(String modulePath) { this.modulePath = modulePath; }

    public Path getBaseDir() { return baseDir; }
    public void setBaseDir(Path baseDir) { this.baseDir = baseDir; }

    public Path getPomFile() { return pomFile; }
    public void setPomFile(Path pomFile) { this.pomFile = pomFile; }

    public List<Path> getSourceRoots() { return sourceRoots; }
    public void setSourceRoots(List<Path> sourceRoots) {
        this.sourceRoots = sourceRoots != null ? sourceRoots : Collections.emptyList();
    }

    public boolean isAggregator() { return aggregator; }
    public void setAggregator(boolean aggregator) { this.aggregator = aggregator; }

    public boolean isApplicationModule() { return applicationModule; }
    public void setApplicationModule(boolean applicationModule) { this.applicationModule = applicationModule; }

    public ModuleType getModuleType() { return moduleType; }
    public void setModuleType(ModuleType moduleType) { this.moduleType = moduleType; }

    public String getCoordinate() {
        return groupId + ":" + artifactId + ":" + version;
    }

    public boolean isPomPackaging() {
        return "pom".equalsIgnoreCase(packaging);
    }

    public String getDisplayName() {
        return modulePath != null && !modulePath.isBlank() ? modulePath : artifactId;
    }

    @Override
    public String toString() {
        return getCoordinate() + " [" + baseDir + "]";
    }
}
