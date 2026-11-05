"""Step 4: build the star schema, the cohort table and the RFM segments, then print the takeaways.
Run:  python -u python/04_star_cohorts_rfm.py
"""
import pandas as pd
from sqlalchemy import text

from db import get_engine
from run_sql import run_file

run_file("sql/04_star.sql")
run_file("sql/04_cohorts_rfm.sql")

engine = get_engine()


def show(title, sql):
    print(f"\n-- {title}", flush=True)
    print(pd.read_sql(text(sql), engine).to_string(index=False), flush=True)


show("Star schema row counts", """
SELECT 'fact_order' AS table, COUNT(*) FROM dw.fact_order
UNION ALL SELECT 'fact_item', COUNT(*) FROM dw.fact_item
UNION ALL SELECT 'dim_customer', COUNT(*) FROM dw.dim_customer
UNION ALL SELECT 'dim_seller', COUNT(*) FROM dw.dim_seller
UNION ALL SELECT 'dim_product', COUNT(*) FROM dw.dim_product
UNION ALL SELECT 'dim_date', COUNT(*) FROM dw.dim_date""")

print("\n-- Cohort retention (% of each first-order month still buying k months later)", flush=True)
cohort = pd.read_sql("""
SELECT to_char(first_month, 'YYYY-MM') AS first_month, cohort_size, months_since_first, pct_active
FROM dw.report_cohort ORDER BY 1, 3""", engine)
wide = cohort.pivot(index=["first_month", "cohort_size"], columns="months_since_first", values="pct_active")
print(wide.round(2).to_string(), flush=True)

show("Average retention by months since first order", """
SELECT months_since_first,
       ROUND(AVG(pct_active), 2) AS avg_pct_active,
       ROUND(MIN(pct_active), 2) AS min_pct,
       ROUND(MAX(pct_active), 2) AS max_pct
FROM dw.report_cohort GROUP BY 1 ORDER BY 1""")

show("RFM segments (snapshot 31 Aug 2018)", """
SELECT segment, people, avg_recency_days, avg_orders, avg_spend, total_spend_k_brl, pct_people, pct_spend
FROM dw.report_rfm_summary ORDER BY segment""")

show("How many people actually ordered twice or more?", """
SELECT CASE WHEN frequency = 1 THEN '1 order'
            WHEN frequency = 2 THEN '2 orders'
            ELSE '3+ orders' END AS orders,
       COUNT(*) AS people,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_people,
       ROUND(SUM(monetary) / 1000, 1) AS spend_k_brl
FROM dw.report_rfm GROUP BY 1 ORDER BY 1""")
