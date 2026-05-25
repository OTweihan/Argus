package com.argus.analyzer.env;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Maven 多模块项目索引。
 *
 * <p>包含所有模块的元信息，支持按 artifactId 查找、
 * 收集所有 source roots、判断某个依赖是否为内部模块。
 */
public class MavenModuleIndex {

    private final Path rootPom;
    private final Path basedir;
    private final List<MavenModule> modules;
    private final Map<String, MavenModule> byArtifactId;
    private final Map<String, MavenModule> byModulePath;

    public MavenModuleIndex(Path rootPom, Path basedir, List<MavenModule> modules) {
        this.rootPom = rootPom;
        this.basedir = basedir;
        this.modules = modules != null ? List.copyOf(modules) : List.of();
        this.byArtifactId = new HashMap<>();
        this.byModulePath = new HashMap<>();
        for (MavenModule m : this.modules) {
            if (m.getArtifactId() != null) {
                byArtifactId.put(m.getArtifactId(), m);
            }
            if (m.getModulePath() != null) {
                byModulePath.put(normalizeModulePath(m.getModulePath()), m);
            }
        }
    }

    /** 根 POM 路径。 */
    public Path getRootPom() { return rootPom; }

    /** 项目根目录（rootPom 的父目录）。 */
    public Path getBasedir() { return basedir; }

    /** 所有模块（含聚合父 POM 模块）。 */
    public List<MavenModule> getModules() { return modules; }

    /** 所有非聚合模块的 source roots（存在磁盘上的）。 */
    public List<Path> getAllSourceRoots() {
        return modules.stream()
                .filter(m -> !m.isAggregator())
                .flatMap(m -> m.getSourceRoots().stream())
                .filter(p -> p != null && Files.exists(p))
                .collect(Collectors.toList());
    }

    /** 所有非聚合模块的 baseDir。 */
    public List<Path> getAllModuleDirs() {
        return modules.stream()
                .filter(m -> !m.isAggregator())
                .map(MavenModule::getBaseDir)
                .filter(Objects::nonNull)
                .filter(Files::isDirectory)
                .collect(Collectors.toList());
    }

    /** 按 artifactId 查找模块。 */
    public Optional<MavenModule> findByArtifactId(String artifactId) {
        return Optional.ofNullable(byArtifactId.get(artifactId));
    }

    /** 按 artifactId、relative path 或 groupId:artifactId 查找模块。 */
    public Optional<MavenModule> findModule(String selector) {
        if (selector == null || selector.isBlank()) {
            return Optional.empty();
        }
        MavenModule byPath = byModulePath.get(normalizeModulePath(selector));
        if (byPath != null) {
            return Optional.of(byPath);
        }
        MavenModule byArtifact = byArtifactId.get(selector);
        if (byArtifact != null) {
            return Optional.of(byArtifact);
        }
        return modules.stream()
                .filter(m -> selector.equals(m.getGroupId() + ":" + m.getArtifactId()))
                .findFirst();
    }

    /** 判断某个 GAV 坐标是否为内部模块。 */
    public boolean isInternalArtifact(String groupId, String artifactId, String version) {
        return modules.stream().anyMatch(m ->
                artifactId.equals(m.getArtifactId()) &&
                (groupId == null || groupId.equals(m.getGroupId())) &&
                (version == null || version.equals(m.getVersion())));
    }

    /** 判断某个 artifactId 是否为内部模块（宽松匹配，只比 artifactId）。 */
    public boolean isInternalArtifactByArtifactId(String artifactId) {
        return byArtifactId.containsKey(artifactId);
    }

    /** 模块数量（含聚合父 POM）。 */
    public int getModuleCount() { return modules.size(); }

    /** 非聚合模块数量。 */
    public int getNonAggregatorModuleCount() {
        return (int) modules.stream().filter(m -> !m.isAggregator()).count();
    }

    /** 按模块类型过滤。 */
    public List<MavenModule> getModulesByType(ModuleType type) {
        return modules.stream()
                .filter(m -> m.getModuleType() == type)
                .toList();
    }

    /** 应用模块数量。 */
    public int getApplicationModuleCount() {
        return getModulesByType(ModuleType.APPLICATION).size();
    }

    /** 业务模块数量。 */
    public int getBusinessModuleCount() {
        return getModulesByType(ModuleType.BUSINESS).size();
    }

    /** 通用/基础设施模块数量。 */
    public int getLibraryModuleCount() {
        return getModulesByType(ModuleType.LIBRARY).size();
    }

    /** BOM 模块数量。 */
    public int getBomModuleCount() {
        return getModulesByType(ModuleType.BOM).size();
    }

    private String normalizeModulePath(String modulePath) {
        return modulePath.replace('\\', '/').replaceAll("/+", "/");
    }

    @Override
    public String toString() {
        return "MavenModuleIndex{rootPom=" + rootPom + ", modules=" + modules.size() + "}";
    }
}
