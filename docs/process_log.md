# Process log (what I found, what I decided, and why)

This log is the honest story of the project: problems found in the real data and how each was handled.

## Step 1: Collection (5 Nov 2026)
**Data:** Olist Brazilian e-commerce (Kaggle), 9 CSV files, about 100,000 real orders from Sep 2016 to Oct 2018.
Loaded unchanged into PostgreSQL schema `raw` (`python/01_load_raw.py`). Row counts match the files exactly.

| Table | Rows |
|---|---|
| customers | 99,441 |
| geolocation | 1,000,163 |
| order_items | 112,650 |
| order_payments | 103,886 |
| order_reviews | 99,224 |
| orders | 99,441 |
| products | 32,951 |
| sellers | 3,095 |
| category_translation | 71 |

### First look: problems found before any analysis
1. **The customer ID trap.** `customer_id` is created fresh for every order (99,441 values for 99,441 orders). The real person is `customer_unique_id` (96,096 people). A cohort or retention table built on `customer_id` would wrongly show nobody ever buys twice. **Decision:** all customer analysis uses `customer_unique_id`.
2. **Very low repeat buying.** Only 2,997 of 96,096 customers (3.1%) ordered more than once. **Meaning:** this is a "first experience" business, so the question is what makes the first order good or bad, not how to reward loyal customers. Any churn model must be judged with precision and recall, not accuracy.
3. **Missing delivery dates.** 2,965 orders have no delivery date; 96,478 of 99,441 orders (97.0%) are `delivered`. **Decision (to confirm in cleaning):** delivery-time analysis uses delivered orders only; undelivered orders are analysed separately, not filled in.
4. **Reviews:** 58.7% have no written comment (41.3% do). 814 duplicate review IDs and 551 orders with more than one review. **Decision (to confirm in cleaning):** one review per order, the latest one.
5. **Language.** Review comments and product categories are in Portuguese. A translation table covers categories; review text will be classified with an LLM and checked against a hand-verified sample.
6. **Products:** 610 products have no category or description fields. **Decision (to confirm):** label as "unknown category", do not guess.
7. **Time range:** orders run Sep 2016 to Oct 2018, so the data is old and Brazilian. This is stated openly in the README.

*(More entries are added after each step: cleaning, EDA, SQL, modelling, GenAI, dashboard.)*
