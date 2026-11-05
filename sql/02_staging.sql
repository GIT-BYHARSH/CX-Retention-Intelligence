-- Step 2b: CLEANING. Builds the `stg` (staging) schema from the untouched `raw` schema.
-- Rule: nothing is deleted silently. Problem rows are FLAGGED, and each decision is logged in stg.cleaning_log.
-- Evidence for every decision: python/02a_diagnose_raw.py and docs/process_log.md.

DROP SCHEMA IF EXISTS stg CASCADE;
CREATE SCHEMA stg;

-- ---------------------------------------------------------------- customers
-- customer_id is created fresh for EVERY order. The real person is customer_unique_id.
CREATE TABLE stg.customers AS
SELECT customer_id,
       customer_unique_id,
       customer_zip_code_prefix AS zip_prefix,
       customer_city            AS city,
       customer_state           AS state
FROM raw.customers;

-- ---------------------------------------------------------------- orders
CREATE TABLE stg.orders AS
WITH t AS (
    SELECT o.order_id,
           o.customer_id,
           c.customer_unique_id,
           o.order_status,
           o.order_purchase_timestamp::timestamp       AS purchase_ts,
           o.order_approved_at::timestamp              AS approved_ts,
           o.order_delivered_carrier_date::timestamp   AS carrier_ts,
           o.order_delivered_customer_date::timestamp  AS delivered_ts,
           o.order_estimated_delivery_date::timestamp  AS estimated_ts
    FROM raw.orders o
    JOIN raw.customers c USING (customer_id)
)
SELECT order_id, customer_id, customer_unique_id, order_status,
       purchase_ts, approved_ts, carrier_ts, delivered_ts, estimated_ts,
       date_trunc('month', purchase_ts)::date AS order_month,
       -- an order counts as delivered only if the status says so AND a delivery date exists
       (order_status = 'delivered' AND delivered_ts IS NOT NULL) AS is_delivered,
       CASE WHEN order_status = 'delivered' AND delivered_ts IS NOT NULL
            THEN ROUND((EXTRACT(EPOCH FROM (delivered_ts - purchase_ts)) / 86400)::numeric, 2) END AS delivery_days,
       -- late = delivered on a later calendar day than promised (comparing dates, not midnight timestamps)
       (order_status = 'delivered' AND delivered_ts IS NOT NULL
            AND delivered_ts::date > estimated_ts::date)  AS is_late,
       CASE WHEN order_status = 'delivered' AND delivered_ts IS NOT NULL
            THEN (delivered_ts::date - estimated_ts::date) END AS days_vs_promise,   -- positive = late
       -- very long deliveries are kept (real customers) but flagged; analyses use medians
       (order_status = 'delivered' AND delivered_ts IS NOT NULL
            AND EXTRACT(EPOCH FROM (delivered_ts - purchase_ts)) / 86400 > 60) AS is_delivery_outlier,
       -- dates that cannot be true (package handed to carrier before the order, or delivered before pickup)
       (carrier_ts < purchase_ts OR delivered_ts < carrier_ts)  AS has_timestamp_issue,
       -- 2016 is almost empty and Sep-Oct 2018 is nearly empty, so cohorts and trends use Jan 2017 - Aug 2018
       (purchase_ts >= '2017-01-01' AND purchase_ts < '2018-09-01') AS in_analysis_window
FROM t;

-- ---------------------------------------------------------------- order items
CREATE TABLE stg.order_items AS
SELECT order_id,
       order_item_id::int            AS item_no,
       product_id,
       seller_id,
       shipping_limit_date::timestamp AS shipping_limit_ts,
       price::numeric                AS price,
       freight_value::numeric        AS freight_value
FROM raw.order_items;

-- one row per order: what the customer bought and paid for (items + freight)
CREATE TABLE stg.order_values AS
SELECT order_id,
       COUNT(*)                     AS n_items,
       COUNT(DISTINCT seller_id)    AS n_sellers,
       SUM(price)                   AS items_value,
       SUM(freight_value)           AS freight_value,
       SUM(price + freight_value)   AS order_value
FROM stg.order_items
GROUP BY order_id;

-- ---------------------------------------------------------------- payments
CREATE TABLE stg.order_payments AS
SELECT order_id,
       payment_sequential::int       AS payment_no,
       payment_type,
       payment_installments::int     AS installments,
       payment_value::numeric        AS payment_value,
       (payment_value::numeric = 0)  AS is_zero_value
FROM raw.order_payments;

-- ---------------------------------------------------------------- reviews
-- 814 duplicate review ids and 547 orders with 2+ reviews: keep ONE review per order, the latest answered.
CREATE TABLE stg.reviews AS
SELECT DISTINCT ON (order_id)
       order_id,
       review_id,
       review_score::int                         AS review_score,
       review_comment_title                      AS comment_title,
       review_comment_message                    AS comment_text,
       (review_comment_message IS NOT NULL AND btrim(review_comment_message) <> '') AS has_comment,
       review_creation_date::timestamp           AS created_ts,
       review_answer_timestamp::timestamp        AS answered_ts
FROM raw.order_reviews
ORDER BY order_id, review_answer_timestamp DESC, review_id;

-- ---------------------------------------------------------------- products
-- 610 products have no category: labelled 'unknown', never guessed. Two categories lack an English name.
CREATE TABLE stg.products AS
SELECT p.product_id,
       p.product_category_name AS category_pt,
       COALESCE(t.product_category_name_english,
                CASE p.product_category_name
                     WHEN 'pc_gamer' THEN 'pc_gamer'
                     WHEN 'portateis_cozinha_e_preparadores_de_alimentos' THEN 'portable_kitchen_food_preparers'
                END,
                'unknown')     AS category,
       p.product_weight_g::numeric   AS weight_g,
       p.product_length_cm::numeric  AS length_cm,
       p.product_height_cm::numeric  AS height_cm,
       p.product_width_cm::numeric   AS width_cm,
       p.product_photos_qty::numeric::int AS photos_qty
FROM raw.products p
LEFT JOIN raw.category_translation t USING (product_category_name);

-- ---------------------------------------------------------------- sellers
CREATE TABLE stg.sellers AS
SELECT seller_id,
       seller_zip_code_prefix AS zip_prefix,
       seller_city            AS city,
       seller_state           AS state
FROM raw.sellers;

-- ---------------------------------------------------------------- geography
-- The raw table has 1,000,163 rows but only 19,015 zip prefixes (many points per zip).
-- One position per zip: the median of points that fall inside Brazil's bounding box.
CREATE TABLE stg.geo_zip AS
SELECT geolocation_zip_code_prefix AS zip_prefix,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY geolocation_lat::numeric) AS lat,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY geolocation_lng::numeric) AS lng,
       COUNT(*) AS n_points
FROM raw.geolocation
WHERE geolocation_lat::numeric BETWEEN -34 AND 6
  AND geolocation_lng::numeric BETWEEN -75 AND -34
GROUP BY geolocation_zip_code_prefix;

-- ---------------------------------------------------------------- indexes
CREATE UNIQUE INDEX ON stg.orders (order_id);
CREATE INDEX ON stg.orders (customer_unique_id);
CREATE INDEX ON stg.order_items (order_id);
CREATE INDEX ON stg.order_items (seller_id);
CREATE INDEX ON stg.order_items (product_id);
CREATE UNIQUE INDEX ON stg.order_values (order_id);
CREATE UNIQUE INDEX ON stg.reviews (order_id);
CREATE UNIQUE INDEX ON stg.products (product_id);
CREATE UNIQUE INDEX ON stg.geo_zip (zip_prefix);
CREATE UNIQUE INDEX ON stg.customers (customer_id);
CREATE UNIQUE INDEX ON stg.sellers (seller_id);

-- ---------------------------------------------------------------- the cleaning log (every decision, with counts)
CREATE TABLE stg.cleaning_log (
    step        int,
    topic       text,
    rows_affected bigint,
    decision    text
);

INSERT INTO stg.cleaning_log VALUES
(1, 'Orders not delivered (no delivery date)',
    (SELECT COUNT(*) FROM stg.orders WHERE NOT is_delivered),
    'Kept in the table. Excluded from delivery-time and late-delivery analysis. Never filled in.'),
(2, 'Delivered orders longer than 60 days (outliers)',
    (SELECT COUNT(*) FROM stg.orders WHERE is_delivery_outlier),
    'Kept (real customers who waited), flagged. Use medians and percentiles, not averages.'),
(3, 'Orders with impossible timestamps',
    (SELECT COUNT(*) FROM stg.orders WHERE has_timestamp_issue),
    'Kept, flagged. Not used for carrier-stage timing.'),
(4, 'Orders outside the Jan 2017 - Aug 2018 window',
    (SELECT COUNT(*) FROM stg.orders WHERE NOT in_analysis_window),
    'Kept, flagged. 2016 and Sep-Oct 2018 are too thin for trends or cohorts.'),
(5, 'Orders with no items',
    (SELECT COUNT(*) FROM stg.orders o WHERE NOT EXISTS (SELECT 1 FROM stg.order_items i WHERE i.order_id = o.order_id)),
    'Kept. Excluded from revenue analysis (nothing was bought).'),
(6, 'Duplicate reviews removed (kept the latest per order)',
    (SELECT COUNT(*) FROM raw.order_reviews) - (SELECT COUNT(*) FROM stg.reviews),
    'One review per order, the latest answered.'),
(7, 'Reviews with no written comment',
    (SELECT COUNT(*) FROM stg.reviews WHERE NOT has_comment),
    'Kept. Text analysis uses only reviews that have a comment.'),
(8, 'Products with no category',
    (SELECT COUNT(*) FROM stg.products WHERE category = 'unknown'),
    'Labelled unknown, not guessed.'),
(9, 'Customers with no map position',
    (SELECT COUNT(*) FROM stg.customers c WHERE NOT EXISTS (SELECT 1 FROM stg.geo_zip g WHERE g.zip_prefix = c.zip_prefix)),
    'Distance features are blank for them; not imputed.'),
(10, 'Sellers with no map position',
    (SELECT COUNT(*) FROM stg.sellers s WHERE NOT EXISTS (SELECT 1 FROM stg.geo_zip g WHERE g.zip_prefix = s.zip_prefix)),
    'Distance features are blank for them; not imputed.'),
(11, 'Payments with a value of zero',
    (SELECT COUNT(*) FROM stg.order_payments WHERE is_zero_value),
    'Kept, flagged. Order value comes from items + freight, not payments.');
