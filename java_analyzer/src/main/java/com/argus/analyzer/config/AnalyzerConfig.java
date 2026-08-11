package com.argus.analyzer.config;

import com.argus.analyzer.application.PassExecutor;
import com.argus.analyzer.application.PlanRegistry;
import com.argus.analyzer.service.CallGraphBuilder;
import com.argus.analyzer.service.CommunityClusterer;
import com.argus.analyzer.service.ControllerExtractor;
import com.argus.analyzer.service.ExecutionFlowTracer;
import com.argus.analyzer.service.FindingDetector;
import com.argus.analyzer.support.SourceFileScanner;
import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadPoolExecutor;

@Configuration
@EnableScheduling
public class AnalyzerConfig {

    @Bean
    public JavaParser javaParser() {
        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        return new JavaParser(config);
    }

    /**
     * 分析 pass 注册表（O-11）：启动时经 {@link PlanValidator} 校验能力图
     * （重复/缺失/循环）。分析算法在此处手工装配，不再声明为 Spring 组件，
     * 保持核心对象为无 Spring 注解的纯 Java 类。
     */
    @Bean
    public PlanRegistry planRegistry(SourceFileScanner sourceFileScanner) {
        return PlanRegistry.of(List.of(
                new ControllerExtractor(sourceFileScanner),
                new CallGraphBuilder(sourceFileScanner),
                new FindingDetector(sourceFileScanner),
                new ExecutionFlowTracer(),
                new CommunityClusterer()
        ));
    }

    @Bean
    public PassExecutor passExecutor(@Qualifier("analysisWorkerExecutor") Executor analysisWorkerExecutor) {
        return new PassExecutor(analysisWorkerExecutor);
    }

    @Bean(name = "analysisJobExecutor")
    public Executor analysisJobExecutor(
            @Value("${argus.analysis.jobs.threads:2}") int threads,
            @Value("${argus.analysis.jobs.queue-capacity:32}") int queueCapacity) {
        return boundedExecutor("argus-analysis-job-", Math.max(1, threads),
                Math.max(0, queueCapacity));
    }

    @Bean(name = "analysisWorkerExecutor")
    public Executor analysisWorkerExecutor(
            @Value("${argus.analysis.workers.threads:0}") int configuredThreads,
            @Value("${argus.analysis.workers.queue-capacity:64}") int queueCapacity) {
        int defaultWorkers = Math.min(8, Math.max(2, Runtime.getRuntime().availableProcessors()));
        int workers = configuredThreads > 0 ? configuredThreads : defaultWorkers;
        return boundedExecutor("argus-analysis-worker-", workers, Math.max(0, queueCapacity));
    }

    @Bean(name = "mavenStreamExecutor", destroyMethod = "close")
    public ExecutorService mavenStreamExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    private ThreadPoolTaskExecutor boundedExecutor(String prefix, int workers, int queueCapacity) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix(prefix);
        executor.setCorePoolSize(workers);
        executor.setMaxPoolSize(workers);
        executor.setQueueCapacity(queueCapacity);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(10);
        executor.initialize();
        return executor;
    }
}
