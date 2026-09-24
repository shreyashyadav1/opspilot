package dev.opspilot.orders.api;

import dev.opspilot.orders.domain.CreateOrderRequest;
import dev.opspilot.orders.domain.Order;
import dev.opspilot.orders.domain.OrderService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {

    private final OrderService orders;

    public OrderController(OrderService orders) {
        this.orders = orders;
    }

    @PostMapping("/orders")
    @ResponseStatus(HttpStatus.CREATED)
    public Order create(@Valid @RequestBody CreateOrderRequest request) {
        return orders.create(request);
    }

    @GetMapping("/orders/{id}")
    public Order get(@PathVariable long id) {
        return orders.find(id);
    }
}
