package com.argus.analyzer.api.dto;

import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class DtoSerializationTest {

    @Autowired
    Validator validator;

    @Test
    void analyzeRequestCanonicalConstructor() {
        var request = new AnalyzeRequest("D:/test/project", "endpoints", null, null);
        assertEquals("D:/test/project", request.sourcePath());
        assertEquals("endpoints", request.scope());
    }

    @Test
    void analyzeRequestTwoArgConstructor() {
        var request = new AnalyzeRequest("D:/test/project", "all");
        assertEquals("D:/test/project", request.sourcePath());
        assertEquals("all", request.scope());
        assertNull(request.targetModules());
        assertNull(request.maven());
    }

    @Test
    void analyzeResponseConstructor() {
        var response = new AnalyzeResponse(
            null, null, null, null, null, null
        );
        assertNull(response.endpoints());
        assertNull(response.diagnostics());
    }

    @Test
    void analyzeRequestValidationBlankSourcePath() {
        var request = new AnalyzeRequest("", "all", null, null);
        var violations = validator.validate(request);
        assertFalse(violations.isEmpty());
        assertTrue(violations.stream().anyMatch(v -> v.getMessage().contains("sourcePath")));
    }
}
