package dev.opspilot.orders.domain;

import java.time.OffsetDateTime;
import java.util.List;

public record Order(
        long id,
        String customerId,
        String status,
        String currency,
        long totalCents,
        String chargeId,
        List<OrderItem> items,
        OffsetDateTime createdAt) {}
