package com.argus.analyzer.api.dto;

import java.util.List;

public record EndpointInfo(
    String path,
    String httpMethod,
    String controllerClass,
    String controllerMethod,
    List<String> parameters,
    String returnType
) {}
