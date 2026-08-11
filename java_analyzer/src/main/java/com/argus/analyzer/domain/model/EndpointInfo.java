package com.argus.analyzer.domain.model;

import java.util.List;

public record EndpointInfo(
    String path,
    String httpMethod,
    String controllerClass,
    String controllerMethod,
    List<String> parameters,
    String returnType
) {}
