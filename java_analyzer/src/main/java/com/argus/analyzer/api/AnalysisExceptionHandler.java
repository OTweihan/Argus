package com.argus.analyzer.api;

import com.argus.analyzer.service.AnalysisJobService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.NoSuchElementException;
import java.util.concurrent.RejectedExecutionException;

/**
 * 分析服务统一异常映射（J3）：作业相关错误映射单点化，Controller 保持薄层。
 * 所有 handler 返回 ProblemDetail，保证各错误路径响应体结构一致。
 */
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

    @ExceptionHandler(NoSuchElementException.class)
    public ProblemDetail handleNotFound(NoSuchElementException error) {
        // 作业不存在（AnalysisJobService 是 NoSuchElementException 的唯一生产方）→ 404。
        ProblemDetail detail = ProblemDetail.forStatusAndDetail(
                HttpStatus.NOT_FOUND,
                error.getMessage() == null ? "Analysis job not found" : error.getMessage()
        );
        detail.setTitle("Analysis job not found");
        return detail;
    }

    @ExceptionHandler(AnalysisJobService.IdempotencyConflictException.class)
    public ProblemDetail handleIdempotencyConflict(AnalysisJobService.IdempotencyConflictException error) {
        // 相同 clientRequestId 但参数指纹不同 → 409。
        ProblemDetail detail = ProblemDetail.forStatusAndDetail(
                HttpStatus.CONFLICT, error.getMessage());
        detail.setTitle("Idempotent resubmission with different parameters");
        return detail;
    }

    @ExceptionHandler(AnalysisJobService.JobNotCompleteException.class)
    public ProblemDetail handleJobNotComplete(AnalysisJobService.JobNotCompleteException error) {
        // 作业未到 SUCCEEDED 即请求结果 → 409。基础设施层的 IllegalStateException
        // 不经此 handler，仍走 Spring 默认 500，避免误报为客户端冲突。
        ProblemDetail detail = ProblemDetail.forStatusAndDetail(
                HttpStatus.CONFLICT, error.getMessage());
        detail.setTitle("Analysis job not complete");
        return detail;
    }
}
