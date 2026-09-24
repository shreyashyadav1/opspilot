package dev.opspilot.orders.domain;

import dev.opspilot.orders.payments.PaymentException;
import dev.opspilot.orders.payments.PaymentsClient;
import org.springframework.stereotype.Service;

@Service
public class OrderService {

    private final OrderRepository repository;
    private final OrderPricing pricing;
    private final PaymentsClient payments;

    public OrderService(OrderRepository repository, OrderPricing pricing, PaymentsClient payments) {
        this.repository = repository;
        this.pricing = pricing;
        this.payments = payments;
    }

    /**
     * Persists the order, then charges it. The payment call happens outside any transaction so a
     * slow payments service never holds a database connection.
     */
    public Order create(CreateOrderRequest request) {
        long total = pricing.totalCents(request.items());
        String currency = request.currencyOrDefault();
        long id = repository.insert(request.customerId(), currency, total, request.items());
        try {
            PaymentsClient.Charge charge = payments.charge(id, total, currency);
            repository.updateStatus(id, "PAID", charge.chargeId());
        } catch (PaymentException e) {
            repository.updateStatus(id, "PAYMENT_FAILED", null);
            throw e;
        }
        return find(id);
    }

    public Order find(long id) {
        return repository.find(id).orElseThrow(() -> new OrderNotFoundException(id));
    }
}
