CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    fullname   VARCHAR(255) NOT NULL,
    email      VARCHAR(255) NOT NULL UNIQUE,
    password   VARCHAR(255) NOT NULL,
    role       VARCHAR(50)  NOT NULL DEFAULT 'BASIC',
    created_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE tables (
    id         SERIAL PRIMARY KEY,
    number     INT       NOT NULL UNIQUE,
    is_active  BOOLEAN   NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE products (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255)   NOT NULL,
    description  TEXT           NOT NULL DEFAULT '',
    price        NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    is_available BOOLEAN        NOT NULL DEFAULT TRUE,
    is_active    BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP      NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP      NOT NULL DEFAULT NOW()
);

CREATE TABLE orders (
    id         SERIAL PRIMARY KEY,
    table_id   INT            NOT NULL REFERENCES tables (id),
    subtotal   NUMERIC(10, 2) NOT NULL CHECK (subtotal >= 0),
    total      NUMERIC(10, 2) NOT NULL CHECK (total >= 0),
    status     VARCHAR(50)    NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'payment_failed', 'canceled')),
    created_at TIMESTAMP      NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP      NOT NULL DEFAULT NOW()
);

CREATE TABLE order_items (
    id         SERIAL PRIMARY KEY,
    order_id   INT            NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    product_id INT            NOT NULL REFERENCES products (id),
    name       VARCHAR(255)   NOT NULL,
    quantity   INT            NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    line_total NUMERIC(10, 2) NOT NULL CHECK (line_total >= 0),
    created_at TIMESTAMP      NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP      NOT NULL DEFAULT NOW()
);

CREATE TABLE payments (
    id                  SERIAL PRIMARY KEY,
    order_id            INT            NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    provider            VARCHAR(50)    NOT NULL DEFAULT 'stripe',
    amount              NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    status              VARCHAR(50)    NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'requires_action', 'paid', 'failed', 'canceled')),
    checkout_session_id VARCHAR(255),
    checkout_url        TEXT,
    provider_payment_id VARCHAR(255),
    created_at          TIMESTAMP      NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP      NOT NULL DEFAULT NOW()
);

CREATE TABLE stripe_events (
    id           SERIAL PRIMARY KEY,
    event_id     VARCHAR(255) NOT NULL UNIQUE,
    event_type   VARCHAR(255) NOT NULL,
    event_object JSONB        NOT NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tables_number ON tables (number);
CREATE INDEX idx_products_active_available ON products (is_active, is_available);

CREATE INDEX idx_orders_table_id ON orders (table_id);
CREATE INDEX idx_orders_status_created_at ON orders (status, created_at DESC);

CREATE INDEX idx_order_items_order_id ON order_items (order_id);
CREATE INDEX idx_order_items_product_id ON order_items (product_id);

CREATE INDEX idx_payments_order_id ON payments (order_id);
CREATE INDEX idx_payments_status_created_at ON payments (status, created_at DESC);
CREATE UNIQUE INDEX ux_payments_checkout_session_id ON payments (checkout_session_id);
CREATE UNIQUE INDEX ux_payments_provider_payment_id ON payments (provider_payment_id);
