package com.argus.analyzer.api;

import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.concurrent.RejectedExecutionException;

@RestControllerAdvice
public class AnalysisExceptionHandler {

    @ExceptionHandler(RejectedExecutionException.class)
    public ProblemDetail handleRejectedExecution(RejectedExecutionException error) {
        ProblemDetail detail = ProblemDetail.forStatusAndDetail(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Analysis capacity is exhausted; retry later"
        );
        detail.setTitle("Analysis service unavailable");
        return detail;
    }
}
