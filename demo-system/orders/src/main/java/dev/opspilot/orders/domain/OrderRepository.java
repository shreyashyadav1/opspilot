package dev.opspilot.orders.domain;

import java.sql.PreparedStatement;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class OrderRepository {

    private final JdbcTemplate jdbc;

    public OrderRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional
    public long insert(String customerId, String currency, long totalCents, List<OrderItem> items) {
        GeneratedKeyHolder keys = new GeneratedKeyHolder();
        jdbc.update(connection -> {
            PreparedStatement ps = connection.prepareStatement(
                    "INSERT INTO orders (customer_id, status, currency, total_cents) VALUES (?, 'PENDING', ?, ?)",
                    new String[] {"id"});
            ps.setString(1, customerId);
            ps.setString(2, currency);
            ps.setLong(3, totalCents);
            return ps;
        }, keys);
        long id = Objects.requireNonNull(keys.getKey()).longValue();
        jdbc.batchUpdate(
                "INSERT INTO order_items (order_id, sku, quantity, unit_price_cents) VALUES (?, ?, ?, ?)",
                items,
                items.size(),
                (ps, item) -> {
                    ps.setLong(1, id);
                    ps.setString(2, item.sku());
                    ps.setInt(3, item.quantity());
                    ps.setLong(4, item.unitPriceCents());
                });
        return id;
    }

    public void updateStatus(long id, String status, String chargeId) {
        jdbc.update(
                "UPDATE orders SET status = ?, charge_id = ?, updated_at = now() WHERE id = ?",
                status, chargeId, id);
    }

    public Optional<Order> find(long id) {
        List<OrderItem> items = jdbc.query(
                "SELECT sku, quantity, unit_price_cents FROM order_items WHERE order_id = ?",
                (rs, n) -> new OrderItem(rs.getString("sku"), rs.getInt("quantity"), rs.getLong("unit_price_cents")),
                id);
        return jdbc.query(
                        "SELECT id, customer_id, status, currency, total_cents, charge_id, created_at FROM orders WHERE id = ?",
                        (rs, n) -> new Order(
                                rs.getLong("id"),
                                rs.getString("customer_id"),
                                rs.getString("status"),
                                rs.getString("currency"),
                                rs.getLong("total_cents"),
                                rs.getString("charge_id"),
                                items,
                                rs.getObject("created_at", OffsetDateTime.class)),
                        id)
                .stream()
                .findFirst();
    }
}
