"""Step 3b (EDA deep dive): test the surprising result properly, then find the sellers and the bad months.
Run:  python -u python/03b_eda_deep_dive.py

1. Repeat purchase with a FAIR follow-up window: only people whose first order is early enough that they
   had a full 180 days to come back (data ends Aug 2018, so first orders up to end of Feb 2018).
2. A significance test and a bootstrap confidence interval, so we say only what the data supports.
3. Seller scorecard (rates, not raw counts, with a minimum volume) and the Feb-Mar 2018 lateness spike.
"""
import math

import numpy as np
import pandas as pd
from sqlalchemy import text

from db import get_engine

engine = get_engine()
rng = np.random.default_rng(42)


def frame(sql):
    return pd.read_sql(text(sql), engine)


# ---------------------------------------------------------------- 1. fair repeat-purchase window
# A "repeat" = another non-cancelled order on a LATER CALENDAR DAY within 180 days of the first order
# (so two orders placed minutes apart, which are really one shopping trip, do not count as loyalty).
people = frame("""
WITH first AS (
    SELECT DISTINCT ON (customer_unique_id) customer_unique_id, order_id, purchase_ts, is_late
    FROM stg.orders WHERE order_status <> 'canceled'
    ORDER BY customer_unique_id, purchase_ts)
SELECT f.customer_unique_id, f.is_late, r.review_score,
       EXISTS (SELECT 1 FROM stg.orders x
               WHERE x.customer_unique_id = f.customer_unique_id AND x.order_status <> 'canceled'
                 AND x.purchase_ts::date > f.purchase_ts::date
                 AND x.purchase_ts <= f.purchase_ts + INTERVAL '180 days') AS repeat_180d
FROM first f
JOIN stg.orders o ON o.order_id = f.order_id AND o.is_delivered
LEFT JOIN stg.reviews r ON r.order_id = f.order_id
WHERE f.purchase_ts >= '2017-01-01' AND f.purchase_ts < '2018-03-01'""")
print(f"People with a delivered first order and a full 180 days to return: {len(people):,}")
print(f"Overall 180-day repeat rate: {people['repeat_180d'].mean() * 100:.2f}%")


def compare(label, a, b, name_a, name_b):
    """Two-proportion z-test plus bootstrap 95% interval for the difference (b minus a)."""
    na, nb = len(a), len(b)
    pa, pb = a.mean(), b.mean()
    pooled = (a.sum() + b.sum()) / (na + nb)
    z = (pb - pa) / math.sqrt(pooled * (1 - pooled) * (1 / na + 1 / nb))
    p_value = math.erfc(abs(z) / math.sqrt(2))
    diffs = [rng.choice(b.to_numpy(), nb).mean() - rng.choice(a.to_numpy(), na).mean() for _ in range(2000)]
    low, high = np.percentile(diffs, [2.5, 97.5])
    print(f"\n{label}")
    print(f"  {name_a}: {pa * 100:.2f}% repeat (n={na:,})   {name_b}: {pb * 100:.2f}% repeat (n={nb:,})")
    print(f"  difference ({name_b} minus {name_a}): {(pb - pa) * 100:+.2f} points, 95% CI [{low * 100:+.2f}, {high * 100:+.2f}], "
          f"p = {p_value:.3f}   -> {'statistically significant' if p_value < 0.05 else 'NOT significant'}")


late = people[people["is_late"]]["repeat_180d"]
ontime = people[~people["is_late"]]["repeat_180d"]
compare("Does a LATE first order lower the chance of coming back?", late, ontime, "late", "on time")

scored = people.dropna(subset=["review_score"])
bad = scored[scored["review_score"] <= 2]["repeat_180d"]
good = scored[scored["review_score"] >= 4]["repeat_180d"]
compare("Does a BAD first review (1-2 stars) lower the chance of coming back?", bad, good, "bad review", "good review")

# ---------------------------------------------------------------- 2. what is a lost repeat order worth?
value = frame("""
SELECT ROUND(AVG(v.order_value)::numeric, 2) AS avg_order_value
FROM stg.order_values v JOIN stg.orders o USING (order_id) WHERE o.in_analysis_window""")
print(f"\nAverage order value: BRL {value.iloc[0, 0]}")

# ---------------------------------------------------------------- 3. seller scorecard
sellers = frame("""
WITH s AS (
    SELECT i.seller_id, COUNT(DISTINCT i.order_id) AS delivered_orders,
           COUNT(DISTINCT i.order_id) FILTER (WHERE o.is_late) AS late_orders,
           COUNT(DISTINCT i.order_id) FILTER (WHERE r.review_score <= 2) AS bad_reviews,
           COUNT(DISTINCT i.order_id) FILTER (WHERE r.review_score IS NOT NULL) AS reviewed_orders
    FROM stg.order_items i JOIN stg.orders o USING (order_id) LEFT JOIN stg.reviews r USING (order_id)
    WHERE o.is_delivered AND o.in_analysis_window GROUP BY 1)
SELECT s.*, se.state FROM s JOIN stg.sellers se USING (seller_id)""")
sellers["late_rate"] = sellers["late_orders"] / sellers["delivered_orders"]
sellers["bad_review_rate"] = sellers["bad_reviews"] / sellers["reviewed_orders"].clip(lower=1)
big = sellers[sellers["delivered_orders"] >= 50].copy()
network_late = sellers["late_orders"].sum() / sellers["delivered_orders"].sum()
print(f"\nNetwork late rate: {network_late * 100:.1f}%. Sellers with 50+ delivered orders: {len(big)} of {len(sellers)}")
worst = big.sort_values("late_rate", ascending=False).head(10)
print("\nTen worst sellers by late rate (50+ delivered orders):")
print(worst[["seller_id", "state", "delivered_orders", "late_rate", "bad_review_rate"]].assign(
    seller_id=lambda d: d["seller_id"].str[:8], late_rate=lambda d: (d["late_rate"] * 100).round(1),
    bad_review_rate=lambda d: (d["bad_review_rate"] * 100).round(1)).to_string(index=False))
flagged = big[big["late_rate"] >= 2 * network_late]
share = flagged["late_orders"].sum() / sellers["late_orders"].sum()
print(f"\nSellers with 50+ orders and a late rate at least double the network ({2 * network_late * 100:.1f}%): "
      f"{len(flagged)} sellers, causing {share * 100:.1f}% of ALL late orders "
      f"({flagged['delivered_orders'].sum() / sellers['delivered_orders'].sum() * 100:.1f}% of all orders).")

# ---------------------------------------------------------------- 4. the Feb-Mar 2018 spike
print("\nFeb-Mar 2018 lateness spike: by customer state vs the rest of 2018 (delivered orders, states with 800+ orders)")
spike = frame("""
SELECT c.state,
       COUNT(*) FILTER (WHERE o.order_month IN ('2018-02-01','2018-03-01')) AS orders_feb_mar,
       ROUND(100.0 * AVG(o.is_late::int) FILTER (WHERE o.order_month IN ('2018-02-01','2018-03-01')), 1) AS late_pct_feb_mar,
       ROUND(100.0 * AVG(o.is_late::int) FILTER (WHERE o.order_month IN ('2018-04-01','2018-05-01','2018-06-01','2018-07-01','2018-08-01')), 1) AS late_pct_apr_aug
FROM stg.orders o JOIN stg.customers c USING (customer_id)
WHERE o.is_delivered AND o.order_month >= '2018-02-01' GROUP BY 1
HAVING COUNT(*) FILTER (WHERE o.order_month IN ('2018-02-01','2018-03-01')) >= 800 ORDER BY 3 DESC""")
print(spike.to_string(index=False))
