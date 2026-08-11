package com.argus.analyzer.application;

import com.argus.analyzer.domain.AnalysisProgressListener;
import com.argus.analyzer.env.ClasspathResult;
import com.argus.analyzer.env.MavenConfig;
import com.argus.analyzer.env.MavenModuleIndex;

import java.nio.file.Path;
import java.util.List;

/**
 * classpath 解析端口（O-11）。
 *
 * <p>应用编排层通过本端口获取 classpath，不直接依赖具体 Maven 解析器/网关。
 * 实现在 infrastructure（{@code env.MavenClasspathResolver}）。返回类型仍为
 * env 侧的 {@link ClasspathResult}（基础设施诊断模型），属当前边界内的务实取舍。</p>
 */
public interface ClasspathResolver {

    /** 非 Maven 模块项目：直接对源码根目录解析。 */
    ClasspathResult resolve(Path sourcePath, MavenConfig config, AnalysisProgressListener progress);

    /** 多模块 Maven 项目：按目标模块解析。 */
    ClasspathResult resolve(MavenModuleIndex moduleIndex, List<String> targetModules,
                            MavenConfig config, AnalysisProgressListener progress);
}
