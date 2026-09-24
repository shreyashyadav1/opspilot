package dev.opspilot.orders.payments;

import dev.opspilot.orders.runtime.RuntimeSettings;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.NestedExceptionUtils;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

/**
 * Calls the payments service. The base URL and timeout come from {@link RuntimeSettings} so a
 * deploy can change them; the client is rebuilt when they do. Built from Spring's
 * auto-configured builder, so calls are measured ({@code http.client.requests}) and traced.
 */
@Component
public class PaymentsClient {

    private static final Logger log = LoggerFactory.getLogger("upstream.payments");
    private static final long SLOW_CALL_MS = 1000;

    public record ChargeRequest(long orderId, long amountCents, String currency) {}

    public record Charge(String chargeId, String status) {}

    private record CachedClient(String baseUrl, int timeoutMs, RestClient client) {}

    private final RestClient.Builder builder;
    private final RuntimeSettings settings;
    private volatile CachedClient cached;

    public PaymentsClient(RestClient.Builder builder, RuntimeSettings settings) {
        this.builder = builder;
        this.settings = settings;
    }

    public Charge charge(long orderId, long amountCents, String currency) {
        long started = System.nanoTime();
        try {
            Charge charge = client().post()
                    .uri("/charges")
                    .body(new ChargeRequest(orderId, amountCents, currency))
                    .retrieve()
                    .body(Charge.class);
            long elapsedMs = (System.nanoTime() - started) / 1_000_000;
            if (elapsedMs > SLOW_CALL_MS) {
                log.atWarn()
                        .addKeyValue("upstream", "payments")
                        .addKeyValue("duration_ms", elapsedMs)
                        .log("Slow call to payments: POST /charges took {} ms", elapsedMs);
            }
            return charge;
        } catch (HttpStatusCodeException e) {
            log.atError()
                    .addKeyValue("upstream", "payments")
                    .addKeyValue("http_status", e.getStatusCode().value())
                    .log("Call to payments returned HTTP {}: POST /charges", e.getStatusCode().value());
            throw new PaymentException("payments returned HTTP " + e.getStatusCode().value(), e);
        } catch (ResourceAccessException e) {
            Throwable cause = NestedExceptionUtils.getMostSpecificCause(e);
            String kind = cause instanceof java.net.SocketTimeoutException ? "timed out" : "failed";
            log.atError()
                    .addKeyValue("upstream", "payments")
                    .addKeyValue("error_type", cause.getClass().getSimpleName())
                    .log("Call to payments {}: {}: {} (POST {}/charges)", kind,
                            cause.getClass().getSimpleName(), cause.getMessage(), settings.paymentsBaseUrl());
            throw new PaymentException("payments call " + kind, e);
        }
    }

    private RestClient client() {
        String baseUrl = settings.paymentsBaseUrl();
        int timeoutMs = settings.paymentsTimeoutMs();
        CachedClient current = cached;
        if (current == null || !current.baseUrl().equals(baseUrl) || current.timeoutMs() != timeoutMs) {
            SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
            factory.setConnectTimeout(Duration.ofMillis(Math.min(timeoutMs, 1000)));
            factory.setReadTimeout(Duration.ofMillis(timeoutMs));
            RestClient client = builder.clone().baseUrl(baseUrl).requestFactory(factory).build();
            current = new CachedClient(baseUrl, timeoutMs, client);
            cached = current;
        }
        return current.client();
    }
}
