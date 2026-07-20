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
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://127.0.0.1:8081/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
