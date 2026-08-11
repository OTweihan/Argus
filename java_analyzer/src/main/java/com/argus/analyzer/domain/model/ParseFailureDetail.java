package com.argus.analyzer.domain.model;

import java.util.List;

public record ParseFailureDetail(String file, List<String> problems) {}
