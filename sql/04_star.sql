-- Step 4a: STAR SCHEMA for analysis and the dashboard.
-- Built from the cleaned staging layer. Grain of fact_order is one order (one customer, one purchase).
-- Dimensions are people, sellers, products, geography and a calendar.

DROP SCHEMA IF EXISTS dw CASCADE;
CREATE SCHEMA dw;

-- ---------------------------------------------------------------- calendar (every day from the first to the last order)
CREATE TABLE dw.dim_date AS
SELECT d::date AS date_id,
       EXTRACT(YEAR  FROM d)::int AS year,
       EXTRACT(MONTH FROM d)::int AS month_number,
       to_char(d, 'YYYY-MM')      AS year_month,
       to_char(d, 'Mon YYYY')     AS month_label,
       EXTRACT(QUARTER FROM d)::int AS quarter,
       to_char(d, 'Day')          AS day_name,
       EXTRACT(ISODOW FROM d)::int AS weekday,
       (d >= '2017-01-01' AND d < '2018-09-01') AS in_analysis_window
FROM generate_series('2016-09-01'::date, '2018-10-31'::date, '1 day') d;

-- ---------------------------------------------------------------- customers (one row per person, not per order)
CREATE TABLE dw.dim_customer AS
SELECT c.customer_unique_id,
       MIN(c.state) AS state,                      -- people with more than one address: first one
       MIN(c.city)  AS city,
       MIN(c.zip_prefix) AS zip_prefix,
       COUNT(*)     AS n_orders_in_raw
FROM stg.customers c
GROUP BY 1;

-- ---------------------------------------------------------------- sellers
CREATE TABLE dw.dim_seller AS
SELECT seller_id, state, city, zip_prefix FROM stg.sellers;

-- ---------------------------------------------------------------- products
CREATE TABLE dw.dim_product AS
SELECT product_id, category, category_pt, weight_g, photos_qty FROM stg.products;

-- ---------------------------------------------------------------- fact: one row per order
CREATE TABLE dw.fact_order AS
SELECT o.order_id,
       o.customer_unique_id,
       o.purchase_ts::date AS purchase_date,
       o.order_month,
       o.order_status,
       o.is_delivered,
       o.is_late,
       o.in_analysis_window,
       o.delivery_days,
       o.days_vs_promise,
       o.has_timestamp_issue,
       o.is_delivery_outlier,
       v.n_items,
       v.n_sellers,
       v.items_value,
       v.freight_value,
       v.order_value,
       r.review_score,
       r.has_comment,
       (r.review_score <= 2) AS is_bad_review,
       p.paid                AS payment_value
FROM stg.orders o
LEFT JOIN stg.order_values v USING (order_id)
LEFT JOIN stg.reviews r USING (order_id)
LEFT JOIN (SELECT order_id, SUM(payment_value) AS paid FROM stg.order_payments GROUP BY 1) p USING (order_id);

-- ---------------------------------------------------------------- fact: one row per item (for category and seller analysis)
CREATE TABLE dw.fact_item AS
SELECT i.order_id,
       i.item_no,
       i.product_id,
       i.seller_id,
       o.customer_unique_id,
       o.purchase_ts::date AS purchase_date,
       o.is_delivered,
       o.is_late,
       o.in_analysis_window,
       i.price,
       i.freight_value,
       p.category
FROM stg.order_items i
JOIN stg.orders o USING (order_id)
JOIN stg.products p USING (product_id);

CREATE UNIQUE INDEX ON dw.dim_date (date_id);
CREATE UNIQUE INDEX ON dw.dim_customer (customer_unique_id);
CREATE UNIQUE INDEX ON dw.dim_seller (seller_id);
CREATE UNIQUE INDEX ON dw.dim_product (product_id);
CREATE UNIQUE INDEX ON dw.fact_order (order_id);
CREATE INDEX ON dw.fact_order (purchase_date);
CREATE INDEX ON dw.fact_order (customer_unique_id);
CREATE INDEX ON dw.fact_item (order_id);
CREATE INDEX ON dw.fact_item (seller_id);
CREATE INDEX ON dw.fact_item (category);
