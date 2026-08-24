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
    void applicationMustNotDependOnApiSpringOrConcreteMavenGateway() {
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.application..")
                .should().dependOnClassesThat().resideInAnyPackage(
                        "com.argus.analyzer.api..",
                        "com.argus.analyzer.env.classpath.gateway..",
                        "com.argus.analyzer.service..",
                        "org.springframework..");
        rule.check(classes);
    }

    @Test
    void enginePassesMustNotDependOnHttpDtos() {
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.service..")
                .and().implement(com.argus.analyzer.domain.AnalysisPass.class)
                .should().dependOnClassesThat().resideInAPackage("com.argus.analyzer.api..");
        rule.check(classes);
    }

    @Test
    void enginePassesMustNotDependOnSpring() {
        // 分析算法（AnalysisPass 实现）不得依赖 Spring Web/Context，保持核心纯 Java。
        // 服务编排类（ProjectAnalyzerService / AnalysisJobService / MavenProcessRegistry）
        // 不是 pass，不受此约束；只有实现 AnalysisPass 的算法类被拦截。
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.service..")
                .and().implement(com.argus.analyzer.domain.AnalysisPass.class)
                .should().dependOnClassesThat().resideInAPackage("org.springframework..");
        rule.check(classes);
    }

    @Test
    void serviceOrchestrationMustNotDependOnHttpDtos() {
        // J1：应用编排层（service）不得依赖 HTTP wire DTO（api.dto）。作业状态/事件
        // 使用 application 层模型（JobStatus/JobEvent），由 api 包的 Mapper 拷贝。
        ArchRule rule = noClasses().that().resideInAPackage("com.argus.analyzer.service..")
                .should().dependOnClassesThat().resideInAPackage("com.argus.analyzer.api..");
        rule.check(classes);
    }
}
