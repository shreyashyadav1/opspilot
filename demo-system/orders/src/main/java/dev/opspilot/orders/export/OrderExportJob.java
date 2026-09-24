package dev.opspilot.orders.export;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Exports recent orders to the analytics warehouse in batches.
 *
 * <p>The {@code pool_exhaustion} failure mode runs the job in a mode where its batch reader never
 * returns connections to the pool: a classic connection leak. The pool drains, request threads
 * time out waiting for a connection, and Hikari's leak detection reports the job's stack. Turning
 * the mode off closes the leaked connections, like a restart would.
 */
@Component
public class OrderExportJob {

    private static final Logger log = LoggerFactory.getLogger(OrderExportJob.class);
    private static final long BATCH_INTERVAL_MS = 300;
    private static final long FAILURE_LOG_INTERVAL_MS = 15_000;

    private final DataSource dataSource;
    private final List<Connection> openCursors = new ArrayList<>();
    private Thread worker;

    public OrderExportJob(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    public synchronized void startLeaking() {
        if (worker != null) {
            return;
        }
        worker = Thread.ofPlatform().name("order-export-worker").daemon().start(this::run);
        log.info("Order export started");
    }

    public synchronized void stop() {
        if (worker == null) {
            return;
        }
        worker.interrupt();
        worker = null;
        for (Connection connection : openCursors) {
            try {
                connection.close();
            } catch (SQLException ignored) {
                // Connection is being discarded anyway.
            }
        }
        openCursors.clear();
        log.info("Order export stopped");
    }

    private void run() {
        long lastFailureLog = 0;
        while (!Thread.currentThread().isInterrupted()) {
            try {
                readBatch();
                Thread.sleep(BATCH_INTERVAL_MS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } catch (SQLException e) {
                long now = System.currentTimeMillis();
                if (now - lastFailureLog > FAILURE_LOG_INTERVAL_MS) {
                    log.warn("Order export batch failed: {}", e.getMessage());
                    lastFailureLog = now;
                }
            }
        }
    }

    private void readBatch() throws SQLException {
        Connection connection = dataSource.getConnection();
        synchronized (this) {
            if (worker == null) {
                connection.close();
                return;
            }
            openCursors.add(connection);
        }
        try (PreparedStatement ps = connection.prepareStatement(
                        "SELECT id, total_cents FROM orders ORDER BY id DESC LIMIT 500");
                ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                // Rows are streamed to the warehouse writer (omitted in the demo).
            }
        }
        // Bug: the connection is kept for the next page and never closed.
    }
}
