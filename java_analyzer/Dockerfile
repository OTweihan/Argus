# Argus Java Analyzer — 多阶段构建
# Stage 1: Maven 编译
FROM eclipse-temurin:21-jdk AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -B dependency:resolve dependency:resolve-plugins
COPY src ./src
RUN mvn -B package -DskipTests

# Stage 2: JRE 运行
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/java-analyzer-*.jar app.jar
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "app.jar"]
