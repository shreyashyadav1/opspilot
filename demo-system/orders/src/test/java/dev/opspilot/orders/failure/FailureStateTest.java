package dev.opspilot.orders.failure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class FailureStateTest {

    @Test
    void neverFailsWhenErrorRateIsZero() {
        FailureState state = new FailureState(() -> 0.0);
        assertThat(state.shouldFail()).isFalse();
    }

    @Test
    void failsWhenRollIsBelowErrorRate() {
        FailureState state = new FailureState(() -> 0.2);
        state.set(new FailureModes(0, 0, 0.3, false, false));
        assertThat(state.shouldFail()).isTrue();
        state.set(new FailureModes(0, 0, 0.1, false, false));
        assertThat(state.shouldFail()).isFalse();
    }

    @Test
    void addedLatencyStaysWithinJitterBounds() {
        FailureState low = new FailureState(() -> 0.0);
        FailureState high = new FailureState(() -> 0.999);
        FailureModes modes = new FailureModes(1000, 200, 0.0, false, false);
        low.set(modes);
        high.set(modes);
        assertThat(low.addedLatencyMs()).isEqualTo(800);
        assertThat(high.addedLatencyMs()).isBetween(1190L, 1200L);
    }

    @Test
    void noLatencyByDefault() {
        assertThat(new FailureState().addedLatencyMs()).isZero();
    }
}
