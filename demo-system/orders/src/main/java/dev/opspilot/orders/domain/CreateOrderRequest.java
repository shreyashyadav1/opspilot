package dev.opspilot.orders.domain;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.List;

public record CreateOrderRequest(
        @NotBlank @Size(max = 64) String customerId,
        @Pattern(regexp = "[A-Z]{3}") String currency,
        @NotEmpty @Size(max = 50) List<@Valid OrderItem> items) {

    public String currencyOrDefault() {
        return currency == null ? "USD" : currency;
    }
}
