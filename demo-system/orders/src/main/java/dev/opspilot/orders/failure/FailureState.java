package dev.opspilot.orders.failure;

import java.util.concurrent.ThreadLocalRandom;
import java.util.function.DoubleSupplier;
import org.springframework.stereotype.Component;

@Component
public class FailureState {

    private final DoubleSupplier random;
    private volatile FailureModes modes = FailureModes.NONE;

    public FailureState() {
        this(() -> ThreadLocalRandom.current().nextDouble());
    }

    FailureState(DoubleSupplier random) {
        this.random = random;
    }

    public FailureModes modes() {
        return modes;
    }

    public void set(FailureModes modes) {
        this.modes = modes;
    }

    /** Rolls the dice for the configured error rate. */
    public boolean shouldFail() {
        double rate = modes.errorRate();
        return rate > 0 && random.getAsDouble() < rate;
    }

    public long addedLatencyMs() {
        FailureModes current = modes;
        if (current.latencyMs() == 0) {
            return 0;
        }
        double jitter = (random.getAsDouble() * 2 - 1) * current.latencyJitterMs();
        return Math.max(0, Math.round(current.latencyMs() + jitter));
    }
}
