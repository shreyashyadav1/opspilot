package dev.opspilot.orders.domain;

import dev.opspilot.orders.failure.FailureState;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class OrderPricing {

    private static final Map<String, BigDecimal> LOYALTY_DISCOUNTS =
            Map.of("default", BigDecimal.ZERO);

    private final FailureState failures;

    public OrderPricing(FailureState failures) {
        this.failures = failures;
    }

    public long totalCents(List<OrderItem> items) {
        BigDecimal subtotal = items.stream()
                .map(i -> BigDecimal.valueOf(i.unitPriceCents()).multiply(BigDecimal.valueOf(i.quantity())))
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        BigDecimal discount = loyaltyDiscount();
        BigDecimal multiplier = BigDecimal.ONE.add(discount.negate());
        return subtotal.multiply(multiplier).setScale(0, RoundingMode.HALF_EVEN).longValueExact();
    }

    private BigDecimal loyaltyDiscount() {
        // The error_spike failure mode sends a share of lookups to a tier with no entry. The
        // missing null check turns that into a genuine NullPointerException in totalCents, so
        // the failure looks exactly like a real regression.
        String tier = failures.shouldFail() ? "gold-2026" : "default";
        return LOYALTY_DISCOUNTS.get(tier);
    }
}
