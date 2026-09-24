package dev.opspilot.orders.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * One structured access log line per business request, in the same shape as the Python
 * services. Ordered after the observation filter so the trace id is in the MDC.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class AccessLogFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger("http.access");

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String uri = request.getRequestURI();
        return uri.startsWith("/admin") || uri.startsWith("/actuator");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        long started = System.nanoTime();
        try {
            chain.doFilter(request, response);
        } finally {
            double durationMs = (System.nanoTime() - started) / 1_000_000.0;
            int status = response.getStatus();
            log.atLevel(status >= 500 ? Level.WARN : Level.INFO)
                    .addKeyValue("http_method", request.getMethod())
                    .addKeyValue("http_path", request.getRequestURI())
                    .addKeyValue("http_status", status)
                    .addKeyValue("duration_ms", Math.round(durationMs * 10) / 10.0)
                    .log("{} {} {} {}ms", request.getMethod(), request.getRequestURI(), status,
                            Math.round(durationMs));
        }
    }
}
