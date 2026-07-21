package com.argus.analyzer.api.dto;

import java.util.List;

public record ParseFailureDetail(String file, List<String> problems) {}
