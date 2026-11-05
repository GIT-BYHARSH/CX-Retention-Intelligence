-- Step 5: one row per delivered, reviewed order, with features known at purchase time.
-- Delivery outcome (is_late, days_vs_promise) is stored for an "oracle" comparison only.
-- Seller and customer history uses ONLY earlier orders (the window stops at 1 PRECEDING).

DROP TABLE IF EXISTS dw.model_orders;

CREATE TABLE dw.model_orders AS
WITH primary_item AS (
    -- one seller/product per order: the most expensive item
    SELECT DISTINCT ON (order_id)
           order_id, seller_id, product_id, shipping_limit_ts
    FROM stg.order_items
    ORDER BY order_id, price DESC, item_no
),
pay AS (
    SELECT DISTINCT ON (order_id)
           order_id, payment_type, installments
    FROM stg.order_payments
    ORDER BY order_id, payment_no
),
base AS (
    SELECT
        o.order_id,
        o.customer_unique_id,
        pi.seller_id,
        o.purchase_ts,
        (r.review_score <= 2)                         AS is_bad_review,
        r.review_score,
        o.is_late,                                    -- NOT a model feature (see python script)
        o.days_vs_promise,
        EXTRACT(EPOCH FROM (o.estimated_ts - o.purchase_ts)) / 86400.0 AS promised_days,
        EXTRACT(EPOCH FROM (pi.shipping_limit_ts - o.purchase_ts)) / 86400.0 AS shipping_limit_days,
        EXTRACT(HOUR FROM o.purchase_ts)::int         AS purchase_hour,
        EXTRACT(ISODOW FROM o.purchase_ts)::int       AS weekday,
        EXTRACT(MONTH FROM o.purchase_ts)::int        AS month_num,
        v.n_items,
        v.n_sellers,
        v.order_value::float                          AS order_value,
        CASE WHEN v.order_value > 0
             THEN (v.freight_value / v.order_value)::float ELSE 0 END AS freight_share,
        COALESCE(pay.payment_type, 'unknown')         AS payment_type,
        COALESCE(pay.installments, 1)                 AS installments,
        c.state                                       AS customer_state,
        s.state                                       AS seller_state,
        (c.state = s.state)                           AS same_state,
        pr.category,
        COALESCE(pr.weight_g, 0)::float               AS weight_g,
        COALESCE(pr.photos_qty, 0)                    AS photos_qty,
        (pr.category = 'office_furniture')            AS is_office_furniture,
        CASE WHEN cg.lat IS NOT NULL AND sg.lat IS NOT NULL THEN
            2 * 6371 * asin(sqrt(
                power(sin(radians(sg.lat - cg.lat) / 2), 2)
                + cos(radians(cg.lat)) * cos(radians(sg.lat))
                  * power(sin(radians(sg.lng - cg.lng) / 2), 2)
            ))
        END                                           AS distance_km
    FROM stg.orders o
    JOIN stg.reviews r          USING (order_id)
    JOIN stg.order_values v     USING (order_id)
    JOIN stg.customers c        USING (customer_id)
    JOIN primary_item pi        USING (order_id)
    JOIN stg.sellers s          ON s.seller_id = pi.seller_id
    JOIN stg.products pr        ON pr.product_id = pi.product_id
    LEFT JOIN pay               USING (order_id)
    LEFT JOIN stg.geo_zip cg    ON cg.zip_prefix = c.zip_prefix
    LEFT JOIN stg.geo_zip sg    ON sg.zip_prefix = s.zip_prefix
    WHERE o.is_delivered
      AND o.in_analysis_window
      AND COALESCE(o.has_timestamp_issue, FALSE) IS FALSE
)
SELECT
    b.*,
    COUNT(*) OVER w_seller AS seller_prior_orders,
    AVG(b.is_late::int) OVER w_seller AS seller_prior_late_rate,
    AVG(b.is_bad_review::int) OVER w_seller AS seller_prior_bad_rate,
    COUNT(*) OVER w_cust AS customer_prior_orders
FROM base b
WINDOW
    w_seller AS (PARTITION BY seller_id ORDER BY purchase_ts
                 ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
    w_cust   AS (PARTITION BY customer_unique_id ORDER BY purchase_ts
                 ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING);

CREATE INDEX ON dw.model_orders (purchase_ts);
CREATE INDEX ON dw.model_orders (seller_id);
