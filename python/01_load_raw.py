"""Step 1 (collection): load the 9 raw Olist CSV files into PostgreSQL, unchanged, in the `raw` schema.

Run from the project root:  python python/01_load_raw.py
Raw data is never edited. All cleaning happens in later steps (SQL staging layer) so every
decision is visible and repeatable.
"""
import pandas as pd
from sqlalchemy import text

from db import PROJECT_ROOT, get_engine

RAW_DIR = PROJECT_ROOT / "data" / "raw"

FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
    for table, filename in FILES.items():
        # Everything is read as text first: raw means raw. Types are applied in the staging layer.
        frame = pd.read_csv(RAW_DIR / filename, dtype=str, keep_default_na=False, na_values=[""])
        frame.to_sql(table, engine, schema="raw", if_exists="replace", index=False,
                     chunksize=20000, method="multi")
        with engine.connect() as conn:
            loaded = conn.execute(text(f"SELECT COUNT(*) FROM raw.{table}")).scalar()
        status = "OK" if loaded == len(frame) else "MISMATCH"
        print(f"raw.{table:22s} {len(frame):>10,} rows in file -> {loaded:>10,} in database  {status}")


if __name__ == "__main__":
    main()
