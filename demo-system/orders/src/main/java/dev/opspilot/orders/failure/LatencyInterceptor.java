package dev.opspilot.orders.failure;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/** Adds the configured delay to business requests. Runs inside observation, so it is measured. */
@Component
public class LatencyInterceptor implements HandlerInterceptor {

    private final FailureState failures;

    public LatencyInterceptor(FailureState failures) {
        this.failures = failures;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws InterruptedException {
        long delay = failures.addedLatencyMs();
        if (delay > 0) {
            Thread.sleep(delay);
        }
        return true;
    }
}
