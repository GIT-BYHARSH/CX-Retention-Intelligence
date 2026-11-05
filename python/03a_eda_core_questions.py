"""Step 3a (EDA): the first business questions, answered with SQL on the cleaned staging layer.
Run:  python -u python/03a_eda_core_questions.py
Window: Jan 2017 - Aug 2018 (in_analysis_window). Customers are people (customer_unique_id).
"""
import pandas as pd
from sqlalchemy import text

from db import get_engine

engine = get_engine()


def show(title, sql):
    print(f"\n-- {title}", flush=True)
    print(pd.read_sql(text(sql), engine).to_string(index=False), flush=True)


show("Q1. Review score by delivery outcome (delivered orders with a review)", """
SELECT CASE WHEN o.days_vs_promise <= 0 THEN '1 on time or early'
            WHEN o.days_vs_promise BETWEEN 1 AND 3 THEN '2 late 1-3 days'
            WHEN o.days_vs_promise BETWEEN 4 AND 7 THEN '3 late 4-7 days'
            ELSE '4 late 8+ days' END AS delivery,
       COUNT(*) AS orders,
       ROUND(AVG(r.review_score), 2) AS avg_score,
       ROUND(100.0 * AVG((r.review_score <= 2)::int), 1) AS pct_bad_reviews
FROM stg.orders o JOIN stg.reviews r USING (order_id)
WHERE o.is_delivered AND o.in_analysis_window
GROUP BY 1 ORDER BY 1""")

show("Q2. Repeat purchase by FIRST order experience (people whose first order was delivered)", """
WITH first_order AS (
    SELECT DISTINCT ON (customer_unique_id) customer_unique_id, order_id, purchase_ts, is_late, days_vs_promise
    FROM stg.orders WHERE in_analysis_window AND order_status <> 'canceled'
    ORDER BY customer_unique_id, purchase_ts),
orders_per_person AS (
    SELECT customer_unique_id, COUNT(*) AS n_orders
    FROM stg.orders WHERE in_analysis_window AND order_status <> 'canceled' GROUP BY 1),
f AS (
    SELECT fo.*, r.review_score, p.n_orders
    FROM first_order fo
    JOIN orders_per_person p USING (customer_unique_id)
    LEFT JOIN stg.reviews r ON r.order_id = fo.order_id
    JOIN stg.orders o ON o.order_id = fo.order_id AND o.is_delivered)
SELECT CASE WHEN review_score IS NULL THEN '0 no review'
            WHEN review_score <= 2 THEN '1 bad first review (1-2)'
            WHEN review_score = 3 THEN '2 neutral (3)'
            ELSE '3 good first review (4-5)' END AS first_experience,
       COUNT(*) AS people,
       ROUND(100.0 * AVG((n_orders > 1)::int), 2) AS pct_ordered_again
FROM f GROUP BY 1 ORDER BY 1""")

show("Q2b. Repeat purchase by whether the FIRST order was late", """
WITH first_order AS (
    SELECT DISTINCT ON (customer_unique_id) customer_unique_id, is_late
    FROM stg.orders WHERE in_analysis_window AND order_status <> 'canceled'
    ORDER BY customer_unique_id, purchase_ts),
n AS (SELECT customer_unique_id, COUNT(*) AS n_orders FROM stg.orders
      WHERE in_analysis_window AND order_status <> 'canceled' GROUP BY 1)
SELECT CASE WHEN f.is_late THEN 'first order late' ELSE 'first order on time or not delivered' END AS first_order,
       COUNT(*) AS people, ROUND(100.0 * AVG((n.n_orders > 1)::int), 2) AS pct_ordered_again
FROM first_order f JOIN n USING (customer_unique_id) GROUP BY 1 ORDER BY 1""")

show("Q3. Monthly orders and value (analysis window)", """
SELECT o.order_month, COUNT(*) AS orders, ROUND(SUM(v.order_value) / 1000, 0) AS value_k_brl
FROM stg.orders o LEFT JOIN stg.order_values v USING (order_id)
WHERE o.in_analysis_window GROUP BY 1 ORDER BY 1""")

show("Q4. Late-delivery rate by month (delivered orders)", """
SELECT order_month, COUNT(*) AS delivered, ROUND(100.0 * AVG(is_late::int), 1) AS pct_late
FROM stg.orders WHERE is_delivered AND in_analysis_window GROUP BY 1 ORDER BY 1""")

show("Q5. Late rate and bad-review rate by customer state (top 10 by orders)", """
SELECT c.state, COUNT(*) AS delivered_orders, ROUND(100.0 * AVG(o.is_late::int), 1) AS pct_late,
       ROUND(100.0 * AVG((r.review_score <= 2)::int), 1) AS pct_bad_reviews,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY o.delivery_days)::numeric, 1) AS median_days
FROM stg.orders o JOIN stg.customers c USING (customer_id) LEFT JOIN stg.reviews r USING (order_id)
WHERE o.is_delivered AND o.in_analysis_window GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")

show("Q6. Where does the money sit? Revenue share by category (top 10)", """
SELECT p.category, COUNT(DISTINCT i.order_id) AS orders, ROUND(SUM(i.price) / 1000, 0) AS items_value_k_brl,
       ROUND(100.0 * SUM(i.price) / SUM(SUM(i.price)) OVER (), 1) AS pct_of_value
FROM stg.order_items i JOIN stg.products p USING (product_id) JOIN stg.orders o USING (order_id)
WHERE o.in_analysis_window GROUP BY 1 ORDER BY 3 DESC LIMIT 10""")

show("Q7. Seller concentration: do a few sellers cause most late deliveries?", """
WITH s AS (
    SELECT i.seller_id, COUNT(DISTINCT i.order_id) AS orders,
           COUNT(DISTINCT i.order_id) FILTER (WHERE o.is_late) AS late_orders
    FROM stg.order_items i JOIN stg.orders o USING (order_id)
    WHERE o.is_delivered AND o.in_analysis_window GROUP BY 1),
ranked AS (SELECT *, SUM(late_orders) OVER (ORDER BY late_orders DESC, seller_id) AS running_late,
                  ROW_NUMBER() OVER (ORDER BY late_orders DESC, seller_id) AS rk FROM s)
SELECT (SELECT COUNT(*) FROM s) AS sellers,
       (SELECT SUM(late_orders) FROM s) AS late_orders_total,
       MAX(rk) FILTER (WHERE running_late <= 0.5 * (SELECT SUM(late_orders) FROM s)) AS sellers_causing_half_of_late_orders
FROM ranked""")
