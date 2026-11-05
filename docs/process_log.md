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

## Step 2: Cleaning (5 Nov 2026)
Measured first (python/02a_diagnose_raw.py), then cleaned in SQL (sql/02_staging.sql, run by python/02b_clean.py).
Rule: **nothing is silently deleted.** Problem rows are flagged and every decision is logged in stg.cleaning_log.

| # | Problem found | Rows | Decision and why |
|---|---|---|---|
| 1 | Orders with no delivery date | 2,971 | Kept, excluded from delivery analysis, never filled in |
| 2 | Deliveries longer than 60 days (median is 10.2 days, longest 209) | 306 | Kept (real customers who waited), flagged. Use medians and percentiles, because averages would be pulled up by these |
| 3 | Impossible timestamps (carrier received it before the order, or delivery before pickup) | 189 | Kept, flagged, not used for carrier-stage timing |
| 4 | Months with almost no orders (2016, Sep-Oct 2018) | 349 | Analysis window is **Jan 2017 to Aug 2018** (20 full months), so trends and cohorts are not distorted by partial months |
| 5 | Orders with no items | 775 | Kept, excluded from revenue analysis |
| 6 | Duplicate reviews (547 orders had 2 or more, 202 of them with different scores) | 551 removed | One review per order, the latest one |
| 7 | Reviews with no written text | 57,907 | Kept; text analysis uses only reviews with a comment |
| 8 | Products with no category | 610 | Labelled "unknown", not guessed |
| 9 | Customers and sellers with no map position | 279 and 7 | Distance left blank, not imputed |
| 10 | Payments with a value of zero | 9 | Kept, flagged; order value comes from items + freight |

**Judgement calls worth explaining in an interview**
- *Late* means delivered on a **later calendar day** than promised. Comparing exact timestamps would call a delivery at 9am "late" against a date promised as midnight. On the calendar-day definition, **6.8%** of delivered orders were late (8.1% on the naive definition).
- 1,000,163 geolocation rows collapse to 19,010 zip positions (the median of the points inside Brazil), so one map position per zip.
- Order value = items + freight (BRL 15.84 million in total). Payments were not used for value because vouchers and zero-value rows make them noisy.

**Reconciliation checks (all pass):** 99,441 orders, 96,096 unique customers, 98,673 orders with a review, 96,470 delivered orders, median delivery 10.2 days.

**Hardest part so far (answer for "what was hard?"):** noticing that customer_id is not a person. Retention built on it would show zero repeat buyers. Using customer_unique_id revealed that only 3.1% of customers ever order twice, which changes the whole business question from loyalty to first experience.
