package com.argus.analyzer.service;

public interface AnalysisProgressListener {

    AnalysisProgressListener NOOP = (stage, level, message) -> {};

    void onEvent(String stage, String level, String message);
}
