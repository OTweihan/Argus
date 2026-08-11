package com.argus.analyzer;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.lang.ArchRule;
import org.junit.jupiter.api.Test;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

/**
 * 包依赖架构约束（O-11）。
 *
 * <p>阻止核心（domain / application）重新引入 Spring、HTTP DTO 或具体 Maven
 * gateway。算法 pass（service/、engine 侧）与 infrastructure 不在本测试的
 * 强制范围，但新增核心代码必须遵守 {@code docs/architecture.md} 的目标边界。</p>
 */
class DependencyRuleTest {

    private final JavaClasses classes = new ClassFileImporter()
            .importPackages("com.argus.analyzer");

    @Test
    void domainMustNotDependOnApiSpringOrInfrastructure() {
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.domain..")
                .should().dependOnClassesThat().resideInAnyPackage(
                        "com.argus.analyzer.api..",
                        "com.argus.analyzer.env..",
                        "com.argus.analyzer.service..",
                        "com.argus.analyzer.support..",
                        "com.argus.analyzer.config..",
                        "org.springframework..");
        rule.check(classes);
    }

    @Test
    void applicationMustNotDependOnApiSpringMvcOrConcreteMavenGateway() {
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.application..")
                .should().dependOnClassesThat().resideInAnyPackage(
                        "com.argus.analyzer.api..",
                        "com.argus.analyzer.env.classpath.gateway..",
                        "com.argus.analyzer.service..",
                        "org.springframework.web..",
                        "org.springframework.stereotype..");
        rule.check(classes);
    }

    @Test
    void enginePassesMustNotDependOnHttpDtos() {
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.service..")
                .and().implement(com.argus.analyzer.domain.AnalysisPass.class)
                .should().dependOnClassesThat().resideInAPackage("com.argus.analyzer.api..");
        rule.check(classes);
    }
}
