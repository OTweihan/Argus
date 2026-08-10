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

    @ExceptionHandler(IllegalArgumentException.class)
    public ProblemDetail handleIllegalArgument(IllegalArgumentException error) {
        // analyze 入口的源码路径边界校验（不存在/非目录/符号链接逃逸/越界）统一 400。
        ProblemDetail detail = ProblemDetail.forStatusAndDetail(
                HttpStatus.BAD_REQUEST,
                error.getMessage() == null ? "Invalid request" : error.getMessage()
        );
        detail.setTitle("Invalid analysis request");
        return detail;
    }
}
