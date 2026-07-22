package com.argus.analyzer.config;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

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
