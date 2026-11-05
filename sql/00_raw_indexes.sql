-- Indexes on the raw tables, only to make the cleaning queries fast. The raw data itself is not changed.
CREATE INDEX IF NOT EXISTS ix_raw_orders_order_id        ON raw.orders (order_id);
CREATE INDEX IF NOT EXISTS ix_raw_orders_customer_id     ON raw.orders (customer_id);
CREATE INDEX IF NOT EXISTS ix_raw_items_order_id         ON raw.order_items (order_id);
CREATE INDEX IF NOT EXISTS ix_raw_items_product_id       ON raw.order_items (product_id);
CREATE INDEX IF NOT EXISTS ix_raw_items_seller_id        ON raw.order_items (seller_id);
CREATE INDEX IF NOT EXISTS ix_raw_payments_order_id      ON raw.order_payments (order_id);
CREATE INDEX IF NOT EXISTS ix_raw_reviews_order_id       ON raw.order_reviews (order_id);
CREATE INDEX IF NOT EXISTS ix_raw_customers_customer_id  ON raw.customers (customer_id);
CREATE INDEX IF NOT EXISTS ix_raw_customers_zip          ON raw.customers (customer_zip_code_prefix);
CREATE INDEX IF NOT EXISTS ix_raw_sellers_seller_id      ON raw.sellers (seller_id);
CREATE INDEX IF NOT EXISTS ix_raw_sellers_zip            ON raw.sellers (seller_zip_code_prefix);
CREATE INDEX IF NOT EXISTS ix_raw_products_product_id    ON raw.products (product_id);
CREATE INDEX IF NOT EXISTS ix_raw_geo_zip                ON raw.geolocation (geolocation_zip_code_prefix);
ANALYZE;
