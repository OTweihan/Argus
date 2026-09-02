package com.argus.analyzer.api;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RequestIdFilterTest {

    @AfterEach
    void clearMdc() {
        MDC.clear();
    }

    @Test
    void reusesIncomingRequestId() throws Exception {
        RequestIdFilter filter = new RequestIdFilter();
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(RequestIdFilter.HEADER, "req_from_python");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, capturingChain("req_from_python"));

        assertEquals("req_from_python", response.getHeader(RequestIdFilter.HEADER));
        assertEquals(null, MDC.get(RequestIdFilter.MDC_KEY));
    }

    @Test
    void generatesRequestIdWhenMissing() throws Exception {
        RequestIdFilter filter = new RequestIdFilter();
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();

        final String[] seen = new String[1];
        filter.doFilter(request, response, (req, res) -> {
            seen[0] = MDC.get(RequestIdFilter.MDC_KEY);
        });

        assertNotNull(seen[0]);
        assertTrue(seen[0].startsWith("req_"));
        assertEquals(seen[0], response.getHeader(RequestIdFilter.HEADER));
        assertFalse(seen[0].isBlank());
    }

    private static FilterChain capturingChain(String expected) {
        return (ServletRequest request, ServletResponse response) -> {
            assertEquals(expected, MDC.get(RequestIdFilter.MDC_KEY));
            assertTrue(request instanceof HttpServletRequest);
            assertTrue(response instanceof HttpServletResponse);
        };
    }
}
