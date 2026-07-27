package com.argus.analyzer.api.dto;

import jakarta.validation.constraints.NotBlank;

public record ValidateSourceRequest(
    @NotBlank(message = "sourcePath is required") String sourcePath
) {}
