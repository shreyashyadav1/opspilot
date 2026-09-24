CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    status      VARCHAR(32) NOT NULL,
    currency    CHAR(3)     NOT NULL,
    total_cents BIGINT      NOT NULL,
    charge_id   VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders (customer_id);

CREATE TABLE IF NOT EXISTS order_items (
    order_id         BIGINT      NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    sku              VARCHAR(32) NOT NULL,
    quantity         INT         NOT NULL CHECK (quantity > 0),
    unit_price_cents BIGINT      NOT NULL CHECK (unit_price_cents >= 0)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items (order_id);
