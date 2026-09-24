package dev.opspilot.orders.failure;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

/**
 * Failure modes the control plane can switch on. Same contract as the Python services, plus
 * {@code poolExhaustion}, which only exists here because only orders owns a connection pool.
 */
public record FailureModes(
        @Min(0) @Max(30_000) int latencyMs,
        @Min(0) @Max(10_000) int latencyJitterMs,
        @DecimalMin("0.0") @DecimalMax("1.0") double errorRate,
        boolean outage,
        boolean poolExhaustion) {

    public static final FailureModes NONE = new FailureModes(0, 0, 0.0, false, false);
}
