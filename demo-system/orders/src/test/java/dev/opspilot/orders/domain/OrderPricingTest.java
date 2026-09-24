package dev.opspilot.orders.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import dev.opspilot.orders.failure.FailureModes;
import dev.opspilot.orders.failure.FailureState;
import java.util.List;
import org.junit.jupiter.api.Test;

class OrderPricingTest {

    private static final List<OrderItem> ITEMS =
            List.of(new OrderItem("SKU-1001", 2, 12999), new OrderItem("SKU-1003", 1, 2899));

    @Test
    void sumsLineItems() {
        OrderPricing pricing = new OrderPricing(new FailureState());
        assertThat(pricing.totalCents(ITEMS)).isEqualTo(2 * 12999 + 2899);
    }

    @Test
    void errorSpikeSurfacesAsNullPointerExceptionFromPricing() {
        FailureState failures = new FailureState();
        failures.set(new FailureModes(0, 0, 1.0, false, false));
        OrderPricing pricing = new OrderPricing(failures);
        assertThatThrownBy(() -> pricing.totalCents(ITEMS))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("discount");
    }
}
