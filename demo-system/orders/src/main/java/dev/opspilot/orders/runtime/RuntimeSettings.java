package dev.opspilot.orders.runtime;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Settings that a deploy can change at runtime through the admin API (version and the keys in
 * {@link #KEYS}). Mirrors the control plane's view of the service's config.
 */
@Component
public class RuntimeSettings {

    public static final String PAYMENTS_BASE_URL = "payments.base-url";
    public static final String PAYMENTS_TIMEOUT_MS = "payments.timeout-ms";
    private static final Map<String, Class<?>> KEYS =
            Map.of(PAYMENTS_BASE_URL, String.class, PAYMENTS_TIMEOUT_MS, Integer.class);

    private volatile String version;
    private volatile String paymentsBaseUrl;
    private volatile int paymentsTimeoutMs;

    public RuntimeSettings(
            @Value("${orders.version}") String version,
            @Value("${orders.payments.base-url}") String paymentsBaseUrl,
            @Value("${orders.payments.timeout-ms}") int paymentsTimeoutMs) {
        this.version = version;
        this.paymentsBaseUrl = paymentsBaseUrl;
        this.paymentsTimeoutMs = paymentsTimeoutMs;
    }

    public String version() {
        return version;
    }

    public String paymentsBaseUrl() {
        return paymentsBaseUrl;
    }

    public int paymentsTimeoutMs() {
        return paymentsTimeoutMs;
    }

    /** Validates every value first, then applies all of them. */
    public synchronized void apply(String newVersion, Map<String, Object> values) {
        for (Map.Entry<String, Object> entry : values.entrySet()) {
            Class<?> expected = KEYS.get(entry.getKey());
            if (expected == null) {
                throw new IllegalArgumentException("unknown config key: " + entry.getKey());
            }
            if (!expected.isInstance(entry.getValue())) {
                throw new IllegalArgumentException(
                        entry.getKey() + " must be of type " + expected.getSimpleName());
            }
        }
        if (values.containsKey(PAYMENTS_TIMEOUT_MS) && (Integer) values.get(PAYMENTS_TIMEOUT_MS) <= 0) {
            throw new IllegalArgumentException(PAYMENTS_TIMEOUT_MS + " must be positive");
        }
        if (values.containsKey(PAYMENTS_BASE_URL)) {
            paymentsBaseUrl = (String) values.get(PAYMENTS_BASE_URL);
        }
        if (values.containsKey(PAYMENTS_TIMEOUT_MS)) {
            paymentsTimeoutMs = (Integer) values.get(PAYMENTS_TIMEOUT_MS);
        }
        if (newVersion != null && !newVersion.isBlank()) {
            version = newVersion;
        }
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> values = new LinkedHashMap<>();
        values.put(PAYMENTS_BASE_URL, paymentsBaseUrl);
        values.put(PAYMENTS_TIMEOUT_MS, paymentsTimeoutMs);
        return values;
    }
}
