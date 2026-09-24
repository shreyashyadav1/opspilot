package dev.opspilot.orders.runtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Map;
import org.junit.jupiter.api.Test;

class RuntimeSettingsTest {

    private final RuntimeSettings settings = new RuntimeSettings("1.8.3", "http://payments:8080", 2000);

    @Test
    void appliesKnownKeysAndVersion() {
        settings.apply("1.8.4", Map.of(RuntimeSettings.PAYMENTS_BASE_URL, "http://payments-v2:8080"));
        assertThat(settings.version()).isEqualTo("1.8.4");
        assertThat(settings.paymentsBaseUrl()).isEqualTo("http://payments-v2:8080");
        assertThat(settings.paymentsTimeoutMs()).isEqualTo(2000);
    }

    @Test
    void rejectsUnknownKeysWithoutApplyingAnything() {
        assertThatThrownBy(() -> settings.apply("9.9.9", Map.of("feature.x", true)))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(settings.version()).isEqualTo("1.8.3");
    }

    @Test
    void rejectsWrongTypes() {
        assertThatThrownBy(() -> settings.apply(null, Map.of(RuntimeSettings.PAYMENTS_TIMEOUT_MS, "fast")))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(settings.paymentsTimeoutMs()).isEqualTo(2000);
    }
}
