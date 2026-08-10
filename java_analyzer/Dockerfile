# Argus Java Analyzer — 多阶段构建
# Stage 1: Maven 编译
FROM eclipse-temurin:21-jdk AS build
WORKDIR /build
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B dependency:resolve dependency:resolve-plugins
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B package -DskipTests

# Stage 2: JRE 运行
FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /build/target/java-analyzer-*.jar app.jar
EXPOSE 8081
# fail-closed：容器内固定只允许分析共享源码目录 /tmp/sources，
# 防止把 Analyzer 当任意目录读取/分析接口使用（allowed-source-roots + symlink 逃逸拒绝）。
ENTRYPOINT ["java", "-Dargus.analysis.allowed-source-roots=/tmp/sources", "-jar", "app.jar"]
