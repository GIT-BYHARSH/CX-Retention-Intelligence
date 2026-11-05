"""Step 2a: measure the data-quality problems in the raw tables BEFORE deciding how to clean them.
Run:  python -u python/02a_diagnose_raw.py     (output is summarised in docs/process_log.md)
"""
import pandas as pd
from sqlalchemy import text

from db import get_engine

engine = get_engine()


def show(title, sql):
    print(f"\n-- {title}", flush=True)
    print(pd.read_sql(text(sql), engine).to_string(index=False), flush=True)


show("Status vs missing delivery date", """
SELECT order_status, COUNT(*) AS n,
       COUNT(*) FILTER (WHERE order_delivered_customer_date IS NULL) AS no_delivery_date
FROM raw.orders GROUP BY 1 ORDER BY 2 DESC""")

show("Timestamps in the wrong order", """
SELECT COUNT(*) FILTER (WHERE order_approved_at::timestamp < order_purchase_timestamp::timestamp) AS approved_before_purchase,
       COUNT(*) FILTER (WHERE order_delivered_carrier_date::timestamp < order_purchase_timestamp::timestamp) AS carrier_before_purchase,
       COUNT(*) FILTER (WHERE order_delivered_customer_date::timestamp < order_delivered_carrier_date::timestamp) AS customer_before_carrier,
       COUNT(*) FILTER (WHERE order_delivered_customer_date::timestamp < order_purchase_timestamp::timestamp) AS customer_before_purchase
FROM raw.orders""")

show("Delivery days (delivered orders): spread and outliers", """
WITH d AS (SELECT EXTRACT(EPOCH FROM (order_delivered_customer_date::timestamp - order_purchase_timestamp::timestamp)) / 86400 AS days
           FROM raw.orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL)
SELECT ROUND(MIN(days)::numeric, 1) AS min_days,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY days)::numeric, 1) AS median_days,
       ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY days)::numeric, 1) AS p95_days,
       ROUND(percentile_cont(0.99) WITHIN GROUP (ORDER BY days)::numeric, 1) AS p99_days,
       ROUND(MAX(days)::numeric, 1) AS max_days,
       COUNT(*) FILTER (WHERE days > 60) AS over_60_days
FROM d""")

show("Late vs on time (delivered orders)", """
SELECT COUNT(*) AS delivered,
       COUNT(*) FILTER (WHERE order_delivered_customer_date::timestamp > order_estimated_delivery_date::timestamp) AS late,
       ROUND(100.0 * COUNT(*) FILTER (WHERE order_delivered_customer_date::timestamp > order_estimated_delivery_date::timestamp) / COUNT(*), 1) AS late_pct
FROM raw.orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL""")

show("Items: price and freight", """
SELECT COUNT(*) AS items, MIN(price::numeric) AS min_price,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY price::numeric)::numeric, 1) AS median_price,
       ROUND(percentile_cont(0.99) WITHIN GROUP (ORDER BY price::numeric)::numeric, 0) AS p99_price,
       MAX(price::numeric) AS max_price,
       COUNT(*) FILTER (WHERE price::numeric <= 0) AS zero_price,
       COUNT(*) FILTER (WHERE freight_value::numeric > price::numeric) AS freight_above_price,
       COUNT(*) FILTER (WHERE freight_value::numeric = 0) AS zero_freight
FROM raw.order_items""")

show("Payments", """
SELECT payment_type, COUNT(*) AS n, COUNT(*) FILTER (WHERE payment_value::numeric = 0) AS zero_value
FROM raw.order_payments GROUP BY 1 ORDER BY 2 DESC""")

show("Orders with no items / no payment / no review", """
SELECT COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM raw.order_items i WHERE i.order_id = o.order_id)) AS no_items,
       COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM raw.order_payments p WHERE p.order_id = o.order_id)) AS no_payment,
       COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM raw.order_reviews r WHERE r.order_id = o.order_id)) AS no_review
FROM raw.orders o""")

show("Product categories with no English translation", """
SELECT p.product_category_name, COUNT(*) AS products FROM raw.products p
LEFT JOIN raw.category_translation t USING (product_category_name)
WHERE p.product_category_name IS NOT NULL AND t.product_category_name_english IS NULL GROUP BY 1""")

show("Geolocation: rows and distinct zip prefixes", """
SELECT COUNT(*) AS rows, COUNT(DISTINCT geolocation_zip_code_prefix) AS zips FROM raw.geolocation""")

show("Customers and sellers whose zip is missing from geolocation", """
SELECT (SELECT COUNT(*) FROM raw.customers c WHERE NOT EXISTS (SELECT 1 FROM raw.geolocation g WHERE g.geolocation_zip_code_prefix = c.customer_zip_code_prefix)) AS customers_no_geo,
       (SELECT COUNT(*) FROM raw.sellers s WHERE NOT EXISTS (SELECT 1 FROM raw.geolocation g WHERE g.geolocation_zip_code_prefix = s.seller_zip_code_prefix)) AS sellers_no_geo""")

show("Reviews: duplicates", """
SELECT COUNT(*) AS reviews, COUNT(DISTINCT review_id) AS distinct_review_ids, COUNT(DISTINCT order_id) AS orders_with_review
FROM raw.order_reviews""")

show("Orders with 2+ reviews: do the scores differ?", """
WITH m AS (SELECT order_id, COUNT(*) AS c, COUNT(DISTINCT review_score) AS s FROM raw.order_reviews GROUP BY 1 HAVING COUNT(*) > 1)
SELECT COUNT(*) AS orders_with_multiple_reviews, COUNT(*) FILTER (WHERE s > 1) AS scores_differ FROM m""")

show("Orders per month (are the first and last months partial?)", """
SELECT to_char(order_purchase_timestamp::timestamp, 'YYYY-MM') AS month, COUNT(*) AS orders
FROM raw.orders GROUP BY 1 ORDER BY 1""")
