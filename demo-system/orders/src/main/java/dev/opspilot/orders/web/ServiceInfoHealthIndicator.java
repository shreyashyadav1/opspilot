package dev.opspilot.orders.web;

import dev.opspilot.orders.runtime.RuntimeSettings;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

/** Adds the running version to /actuator/health so health checks report what is deployed. */
@Component("service")
public class ServiceInfoHealthIndicator implements HealthIndicator {

    private final RuntimeSettings settings;

    public ServiceInfoHealthIndicator(RuntimeSettings settings) {
        this.settings = settings;
    }

    @Override
    public Health health() {
        return Health.up().withDetail("name", "orders").withDetail("version", settings.version()).build();
    }
}
