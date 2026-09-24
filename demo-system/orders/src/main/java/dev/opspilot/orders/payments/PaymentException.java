package dev.opspilot.orders.payments;

public class PaymentException extends RuntimeException {

    public PaymentException(String message, Throwable cause) {
        super(message, cause);
    }
}
