package dev.opspilot.orders.api;

import dev.opspilot.orders.domain.OrderNotFoundException;
import dev.opspilot.orders.payments.PaymentException;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.NestedExceptionUtils;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger("http.server");

    @ExceptionHandler(OrderNotFoundException.class)
    ResponseEntity<Map<String, String>> notFound(OrderNotFoundException e) {
        return body(HttpStatus.NOT_FOUND, "not_found", e.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Map<String, String>> invalid(MethodArgumentNotValidException e) {
        return body(HttpStatus.BAD_REQUEST, "invalid_request", e.getBindingResult().toString());
    }

    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<Map<String, String>> status(ResponseStatusException e) {
        return body(HttpStatus.valueOf(e.getStatusCode().value()), "request_failed", e.getReason());
    }

    @ExceptionHandler(PaymentException.class)
    ResponseEntity<Map<String, String>> payment(PaymentException e, HttpServletRequest request) {
        log.atWarn()
                .addKeyValue("http_method", request.getMethod())
                .addKeyValue("http_path", request.getRequestURI())
                .log("Order could not be completed: {}", e.getMessage());
        return body(HttpStatus.BAD_GATEWAY, "payment_failed", e.getMessage());
    }

    /** Covers both query failures and failures to obtain a connection for a transaction. */
    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    ResponseEntity<Map<String, String>> database(RuntimeException e, HttpServletRequest request) {
        Throwable cause = NestedExceptionUtils.getMostSpecificCause(e);
        log.atError()
                .addKeyValue("http_method", request.getMethod())
                .addKeyValue("http_path", request.getRequestURI())
                .addKeyValue("error_type", cause.getClass().getSimpleName())
                .log("Database access failed on {} {}: {}", request.getMethod(), request.getRequestURI(),
                        cause.getMessage());
        return body(HttpStatus.SERVICE_UNAVAILABLE, "database_unavailable", "database access failed");
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Map<String, String>> unexpected(Exception e, HttpServletRequest request) {
        log.atError()
                .addKeyValue("http_method", request.getMethod())
                .addKeyValue("http_path", request.getRequestURI())
                .addKeyValue("error_type", e.getClass().getSimpleName())
                .setCause(e)
                .log("Unhandled exception while handling {} {}", request.getMethod(), request.getRequestURI());
        return body(HttpStatus.INTERNAL_SERVER_ERROR, "internal_error", "unexpected error");
    }

    private static ResponseEntity<Map<String, String>> body(HttpStatus status, String error, String detail) {
        return ResponseEntity.status(status).body(Map.of("error", error, "detail", detail == null ? "" : detail));
    }
}
