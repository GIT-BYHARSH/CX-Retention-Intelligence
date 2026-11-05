-- Step 4b: COHORT RETENTION and RFM SEGMENTS.
-- Snapshot date: 31 Aug 2018 (end of the analysis window). Recency is days since last order.
-- Frequency is NOT scored with NTILE. Almost every customer has one order, so quintiles would
-- split identical people at random. Frequency is scored from the actual count instead.

DROP TABLE IF EXISTS dw.report_cohort;
DROP TABLE IF EXISTS dw.report_rfm;
DROP TABLE IF EXISTS dw.report_rfm_summary;
DROP TABLE IF EXISTS dw.customer_order_seq;

CREATE TABLE dw.customer_order_seq AS
SELECT o.customer_unique_id,
       o.order_id,
       o.purchase_ts,
       o.purchase_ts::date AS purchase_date,
       MIN(o.purchase_ts) OVER (PARTITION BY o.customer_unique_id) AS first_ts,
       date_trunc('month', MIN(o.purchase_ts) OVER (PARTITION BY o.customer_unique_id))::date AS first_month,
       ROW_NUMBER() OVER (PARTITION BY o.customer_unique_id ORDER BY o.purchase_ts, o.order_id) AS order_n,
       (EXTRACT(YEAR  FROM o.purchase_ts)
      - EXTRACT(YEAR  FROM MIN(o.purchase_ts) OVER (PARTITION BY o.customer_unique_id))) * 12
     + (EXTRACT(MONTH FROM o.purchase_ts)
      - EXTRACT(MONTH FROM MIN(o.purchase_ts) OVER (PARTITION BY o.customer_unique_id))) AS months_since_first
FROM stg.orders o
WHERE o.in_analysis_window AND o.order_status <> 'canceled';

CREATE INDEX ON dw.customer_order_seq (customer_unique_id);
CREATE INDEX ON dw.customer_order_seq (first_month);

-- Of people whose FIRST order was in month M, what share had an order k months later?
-- Month 0 is always 100% (the first order). Later months count a later calendar-day order.
CREATE TABLE dw.report_cohort AS
WITH firsts AS (
    SELECT customer_unique_id, first_month, purchase_date AS first_date
    FROM dw.customer_order_seq
    WHERE order_n = 1 AND first_month >= '2017-01-01' AND first_month <= '2018-02-01'
),
sizes AS (
    SELECT first_month, COUNT(*) AS cohort_size FROM firsts GROUP BY 1
),
activity AS (
    SELECT f.first_month,
           s.months_since_first,
           COUNT(DISTINCT s.customer_unique_id) AS active
    FROM firsts f
    JOIN dw.customer_order_seq s ON s.customer_unique_id = f.customer_unique_id
    WHERE s.months_since_first BETWEEN 0 AND 6
      AND (s.months_since_first = 0 OR s.purchase_date > f.first_date)
    GROUP BY 1, 2
)
SELECT a.first_month,
       sz.cohort_size,
       a.months_since_first,
       a.active,
       ROUND(100.0 * a.active / sz.cohort_size, 2) AS pct_active
FROM activity a JOIN sizes sz USING (first_month)
ORDER BY 1, 3;

CREATE TABLE dw.report_rfm AS
WITH base AS (
    SELECT o.customer_unique_id,
           MAX(o.purchase_ts::date) AS last_order_date,
           ('2018-08-31'::date - MAX(o.purchase_ts::date)) AS recency_days,
           COUNT(*) AS frequency,
           COALESCE(SUM(v.order_value), 0) AS monetary
    FROM stg.orders o
    LEFT JOIN stg.order_values v USING (order_id)
    WHERE o.in_analysis_window AND o.order_status <> 'canceled'
    GROUP BY 1
),
scored AS (
    SELECT *,
           NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,   -- 5 = most recent
           CASE WHEN frequency >= 3 THEN 5
                WHEN frequency = 2 THEN 3
                ELSE 1 END AS f_score,                              -- real counts, not quintiles
           NTILE(5) OVER (ORDER BY monetary) AS m_score             -- 5 = highest spend
    FROM base
)
SELECT customer_unique_id, last_order_date, recency_days, frequency, monetary,
       r_score, f_score, m_score,
       CASE
           WHEN frequency >= 2 AND r_score >= 4 AND m_score >= 4 THEN '1 Champions (repeat, recent, high spend)'
           WHEN frequency >= 2 AND r_score >= 4                 THEN '2 Loyal repeaters (recent)'
           WHEN frequency >= 2 AND r_score <= 2                 THEN '3 At-risk repeaters (used to come back)'
           WHEN frequency >= 2                                  THEN '4 Quiet repeaters'
           WHEN frequency = 1 AND r_score >= 4 AND m_score >= 4 THEN '5 Recent high-value first-timers'
           WHEN frequency = 1 AND r_score >= 4                  THEN '6 Recent first-timers'
           WHEN frequency = 1 AND r_score <= 2 AND m_score >= 4 THEN '7 Lapsed high-value one-timers'
           ELSE '8 Lapsed one-timers'
       END AS segment
FROM scored;

CREATE TABLE dw.report_rfm_summary AS
SELECT segment,
       COUNT(*) AS people,
       ROUND(AVG(recency_days)::numeric, 0) AS avg_recency_days,
       ROUND(AVG(frequency)::numeric, 2)    AS avg_orders,
       ROUND(AVG(monetary)::numeric, 0)     AS avg_spend,
       ROUND(SUM(monetary)::numeric / 1000, 1) AS total_spend_k_brl,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_people,
       ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 1) AS pct_spend
FROM dw.report_rfm
GROUP BY 1
ORDER BY segment;
