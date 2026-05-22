package com.argus.analyzer.config;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AnalyzerConfig {

    @Bean
    public JavaParser javaParser() {
        ParserConfiguration config = new ParserConfiguration();
        config.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        return new JavaParser(config);
    }
}
