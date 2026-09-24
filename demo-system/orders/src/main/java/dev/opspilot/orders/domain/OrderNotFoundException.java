package dev.opspilot.orders.domain;

public class OrderNotFoundException extends RuntimeException {

    public OrderNotFoundException(long id) {
        super("order " + id + " not found");
    }
}
