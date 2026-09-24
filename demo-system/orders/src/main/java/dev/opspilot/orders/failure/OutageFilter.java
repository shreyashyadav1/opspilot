package dev.opspilot.orders.failure;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Makes the service unavailable during an outage. Runs before observation so an unavailable
 * instance emits nothing: no request metrics, no logs, and Prometheus scrapes fail.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class OutageFilter extends OncePerRequestFilter {

    private final FailureState failures;

    public OutageFilter(FailureState failures) {
        this.failures = failures;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        if (failures.modes().outage() && !request.getRequestURI().startsWith("/admin")) {
            response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\":\"service_unavailable\"}");
            return;
        }
        chain.doFilter(request, response);
    }
}
