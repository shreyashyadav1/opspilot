# Build inside Docker so no local JDK or Maven is required.
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
ENV MAVEN_OPTS="-Xmx512m"
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn -B -q dependency:go-offline
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn -B -q package

FROM eclipse-temurin:21-jre
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /build/target/orders.jar /app/orders.jar
USER app
# Small, predictable footprint: the demo stack shares a few GB of RAM.
ENV JAVA_OPTS="-Xmx256m -Xss512k -XX:MaxMetaspaceSize=128m -XX:+UseSerialGC -XX:TieredStopAtLevel=1"
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/orders.jar"]
