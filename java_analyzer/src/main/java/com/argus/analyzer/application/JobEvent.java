package com.argus.analyzer.application;

import java.time.Instant;

/**
 * 作业进度事件（应用层模型，J1）。
 *
 * <p>作业状态机的事件词汇：stage/level 为开放字符串值（与 wire 契约保持一致），
 * 由 HTTP adapter 映射为 {@code api.dto.AnalysisJobEvent}；应用编排层不依赖
 * HTTP DTO。</p>
 */
public record JobEvent(
        Instant timestamp,
        String stage,
        String level,
        String message,
        int sequence,
        String eventId
) {}
