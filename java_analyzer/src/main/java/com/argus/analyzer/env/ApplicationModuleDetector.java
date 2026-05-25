package com.argus.analyzer.env;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

/**
 * 应用模块自动检测器。
 *
 * <p>已废弃，请使用 {@link ModuleClassifier}。
 * 保留此类仅为 API 兼容，内部委托给 ModuleClassifier。
 */
@Deprecated
@Component
public class ApplicationModuleDetector {

    private static final Logger log = LoggerFactory.getLogger(ApplicationModuleDetector.class);

    private final ModuleClassifier classifier;

    public ApplicationModuleDetector(ModuleClassifier classifier) {
        this.classifier = classifier;
    }

    /**
     * 从模块索引中自动检测应用模块。
     *
     * @deprecated 使用 {@link ModuleClassifier#selectTargets(MavenModuleIndex)}
     */
    @Deprecated
    public List<String> detect(MavenModuleIndex moduleIndex) {
        log.info("[APP_DETECTOR] Delegating to ModuleClassifier (deprecated path)");
        classifier.classifyAll(moduleIndex);
        return classifier.selectTargets(moduleIndex).stream()
                .map(MavenModule::getDisplayName)
                .toList();
    }
}
