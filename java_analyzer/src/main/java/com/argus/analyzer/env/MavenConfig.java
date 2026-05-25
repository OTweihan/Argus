package com.argus.analyzer.env;

public class MavenConfig {

    private boolean autoDetect = true;
    private boolean generateClasspath = true;
    private String classpathFile;
    private String executable;
    private String settingsXml;
    private String localRepository;
    private boolean offline;
    private String dependencyPluginVersion = "3.6.1";
    private long offlineTimeoutSeconds = 45;
    private long onlineTimeoutSeconds = 180;
    private ClasspathMode classpathMode = ClasspathMode.AUTO;
    private boolean prepareReactorArtifacts = false;

    public MavenConfig() {}

    public MavenConfig(boolean autoDetect, boolean generateClasspath,
                       String classpathFile, String executable,
                       String settingsXml, String localRepository, boolean offline) {
        this.autoDetect = autoDetect;
        this.generateClasspath = generateClasspath;
        this.classpathFile = classpathFile;
        this.executable = executable;
        this.settingsXml = settingsXml;
        this.localRepository = localRepository;
        this.offline = offline;
    }

    public boolean isAutoDetect() { return autoDetect; }
    public void setAutoDetect(boolean autoDetect) { this.autoDetect = autoDetect; }

    public boolean isGenerateClasspath() { return generateClasspath; }
    public void setGenerateClasspath(boolean generateClasspath) { this.generateClasspath = generateClasspath; }

    public String getClasspathFile() { return classpathFile; }
    public void setClasspathFile(String classpathFile) { this.classpathFile = classpathFile; }

    public String getExecutable() { return executable; }
    public void setExecutable(String executable) { this.executable = executable; }

    public String getSettingsXml() { return settingsXml; }
    public void setSettingsXml(String settingsXml) { this.settingsXml = settingsXml; }

    public String getLocalRepository() { return localRepository; }
    public void setLocalRepository(String localRepository) { this.localRepository = localRepository; }

    public boolean isOffline() { return offline; }
    public void setOffline(boolean offline) { this.offline = offline; }

    public String getDependencyPluginVersion() { return dependencyPluginVersion; }
    public void setDependencyPluginVersion(String dependencyPluginVersion) { this.dependencyPluginVersion = dependencyPluginVersion; }

    public long getOfflineTimeoutSeconds() { return offlineTimeoutSeconds; }
    public void setOfflineTimeoutSeconds(long offlineTimeoutSeconds) { this.offlineTimeoutSeconds = offlineTimeoutSeconds; }

    public long getOnlineTimeoutSeconds() { return onlineTimeoutSeconds; }
    public void setOnlineTimeoutSeconds(long onlineTimeoutSeconds) { this.onlineTimeoutSeconds = onlineTimeoutSeconds; }

    public ClasspathMode getClasspathMode() { return classpathMode; }
    public void setClasspathMode(ClasspathMode classpathMode) { this.classpathMode = classpathMode; }

    public boolean isPrepareReactorArtifacts() { return prepareReactorArtifacts; }
    public void setPrepareReactorArtifacts(boolean prepareReactorArtifacts) { this.prepareReactorArtifacts = prepareReactorArtifacts; }

    /** 克隆当前配置并切换离线/在线模式。 */
    public MavenConfig withOffline(boolean offline) {
        MavenConfig clone = new MavenConfig();
        clone.autoDetect = this.autoDetect;
        clone.generateClasspath = this.generateClasspath;
        clone.classpathFile = this.classpathFile;
        clone.executable = this.executable;
        clone.settingsXml = this.settingsXml;
        clone.localRepository = this.localRepository;
        clone.offline = offline;
        clone.dependencyPluginVersion = this.dependencyPluginVersion;
        clone.offlineTimeoutSeconds = this.offlineTimeoutSeconds;
        clone.onlineTimeoutSeconds = this.onlineTimeoutSeconds;
        clone.classpathMode = this.classpathMode;
        clone.prepareReactorArtifacts = this.prepareReactorArtifacts;
        return clone;
    }
}
