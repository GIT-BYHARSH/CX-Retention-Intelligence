"""Step 3c (EDA): size the money. Which kinds of failure actually cost revenue?
Run:  python -u python/03c_revenue_at_risk.py
Revenue = items + freight (BRL). Window: Jan 2017 - Aug 2018.
"""
import pandas as pd
from sqlalchemy import text

from db import get_engine

engine = get_engine()


def show(title, sql):
    print(f"\n-- {title}", flush=True)
    print(pd.read_sql(text(sql), engine).to_string(index=False), flush=True)


show("A. Orders that were never delivered, by status: how many, how much money, how old", """
SELECT o.order_status,
       COUNT(*) AS orders,
       COUNT(v.order_id) AS orders_with_items,
       ROUND(COALESCE(SUM(v.order_value), 0)::numeric / 1000, 1) AS order_value_k_brl,
       ROUND(COALESCE(SUM(p.paid), 0)::numeric / 1000, 1) AS customer_payments_k_brl,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY ('2018-10-17'::date - o.purchase_ts::date))::numeric, 0) AS median_age_days
FROM stg.orders o
LEFT JOIN stg.order_values v USING (order_id)
LEFT JOIN (SELECT order_id, SUM(payment_value) AS paid FROM stg.order_payments GROUP BY 1) p USING (order_id)
WHERE NOT o.is_delivered AND o.in_analysis_window
GROUP BY 1 ORDER BY 3 DESC""")

show("B. Orders stuck in 'shipped' for more than 60 days (likely lost in transit)", """
SELECT COUNT(*) AS stuck_orders,
       ROUND(COALESCE(SUM(v.order_value), 0)::numeric / 1000, 1) AS order_value_k_brl
FROM stg.orders o LEFT JOIN stg.order_values v USING (order_id)
WHERE o.order_status = 'shipped' AND o.in_analysis_window AND o.purchase_ts < '2018-08-29'::date - 60""")

show("C. Share of all order value that failed (not delivered) vs total", """
SELECT ROUND(SUM(v.order_value) FILTER (WHERE NOT o.is_delivered)::numeric / 1000, 1) AS failed_value_k_brl,
       ROUND(SUM(v.order_value)::numeric / 1000, 1) AS total_value_k_brl,
       ROUND(100.0 * SUM(v.order_value) FILTER (WHERE NOT o.is_delivered) / SUM(v.order_value), 2) AS failed_pct_of_value
FROM stg.orders o JOIN stg.order_values v USING (order_id) WHERE o.in_analysis_window""")

show("D. Delivered but terrible: bad reviews by delivery lateness, with order value", """
SELECT CASE WHEN o.days_vs_promise <= 0 THEN 'on time' ELSE 'late' END AS delivery,
       COUNT(*) AS orders,
       SUM((r.review_score <= 2)::int) AS bad_reviews,
       ROUND(100.0 * AVG((r.review_score <= 2)::int), 1) AS pct_bad,
       ROUND(AVG(v.order_value)::numeric, 1) AS avg_order_value
FROM stg.orders o JOIN stg.reviews r USING (order_id) JOIN stg.order_values v USING (order_id)
WHERE o.is_delivered AND o.in_analysis_window GROUP BY 1 ORDER BY 1""")

show("E. What drives bad reviews OTHER than lateness? Bad-review rate for ON-TIME orders by category (800+ orders)", """
SELECT p.category, COUNT(DISTINCT o.order_id) AS orders,
       ROUND(100.0 * AVG((r.review_score <= 2)::int), 1) AS pct_bad_reviews
FROM stg.orders o JOIN stg.reviews r USING (order_id)
JOIN stg.order_items i USING (order_id) JOIN stg.products p USING (product_id)
WHERE o.is_delivered AND o.in_analysis_window AND NOT o.is_late
GROUP BY 1 HAVING COUNT(DISTINCT o.order_id) >= 800 ORDER BY 3 DESC LIMIT 8""")
