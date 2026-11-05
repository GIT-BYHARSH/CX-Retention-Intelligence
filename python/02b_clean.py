"""Step 2b: run the cleaning SQL, then print the cleaning log and reconciliation checks.
Run:  python -u python/02b_clean.py
"""
import pandas as pd
from sqlalchemy import text

from db import get_engine
from run_sql import run_file

run_file("sql/02_staging.sql")

engine = get_engine()
print("\n== Cleaning log ==")
print(pd.read_sql("SELECT step, topic, rows_affected FROM stg.cleaning_log ORDER BY step", engine).to_string(index=False))

checks = {
    "stg.orders rows (expect 99,441)": "SELECT COUNT(*) FROM stg.orders",
    "unique customers (expect 96,096)": "SELECT COUNT(DISTINCT customer_unique_id) FROM stg.orders",
    "orders with a review (expect 98,673)": "SELECT COUNT(*) FROM stg.reviews",
    "orders in analysis window": "SELECT COUNT(*) FROM stg.orders WHERE in_analysis_window",
    "delivered orders": "SELECT COUNT(*) FROM stg.orders WHERE is_delivered",
    "late share of delivered (%)": "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*), 1) FROM stg.orders WHERE is_delivered",
    "median delivery days": "SELECT ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY delivery_days)::numeric, 1) FROM stg.orders WHERE is_delivered",
    "zip prefixes with a position": "SELECT COUNT(*) FROM stg.geo_zip",
    "total order value, BRL millions": "SELECT ROUND(SUM(order_value) / 1e6, 2) FROM stg.order_values",
}
print("\n== Checks ==")
with engine.connect() as conn:
    for label, sql in checks.items():
        print(f"{label:42s} {conn.execute(text(sql)).scalar():>12,}" if label.endswith(("rows (expect 99,441)", "(expect 96,096)", "(expect 98,673)", "window", "delivered orders", "prefixes with a position"))
              else f"{label:42s} {conn.execute(text(sql)).scalar()}")
