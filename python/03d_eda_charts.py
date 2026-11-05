"""Step 3d: EDA charts. Every chart title states the takeaway (the "so what"), not just the topic.
Run:  python -u python/03d_eda_charts.py      Output: assets/eda/*.png
"""
import math
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db import PROJECT_ROOT, get_engine  # noqa: E402

OUT = PROJECT_ROOT / "assets" / "eda"
OUT.mkdir(parents=True, exist_ok=True)
engine = get_engine()
BLUE, RED, GREY = "#2f6db5", "#c0392b", "#9aa5b1"

plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def q(sql):
    return pd.read_sql(text(sql), engine)


def save(fig, name, footnote):
    wrapped = textwrap.fill(footnote, width=int(fig.get_figwidth() * 13))
    fig.text(0.01, 0.005, wrapped, fontsize=8.5, color="#555555", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03 + 0.025 * wrapped.count("\n"), 1, 1))
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("saved", name, flush=True)


# 1. Bad reviews by delivery outcome ------------------------------------------------------------
d = q("""SELECT CASE WHEN o.days_vs_promise <= 0 THEN 'On time\nor early'
                    WHEN o.days_vs_promise BETWEEN 1 AND 3 THEN 'Late\n1-3 days'
                    WHEN o.days_vs_promise BETWEEN 4 AND 7 THEN 'Late\n4-7 days' ELSE 'Late\n8+ days' END AS delivery,
               MIN(o.days_vs_promise) AS sort_key, COUNT(*) AS orders,
               ROUND(100.0 * AVG((r.review_score <= 2)::int), 1) AS pct_bad
        FROM stg.orders o JOIN stg.reviews r USING (order_id)
        WHERE o.is_delivered AND o.in_analysis_window GROUP BY 1 ORDER BY 2""")
fig, ax = plt.subplots(figsize=(8, 4.6))
bars = ax.bar(d["delivery"], d["pct_bad"], color=[BLUE, "#e0a458", "#d9822b", RED])
for b, v, n in zip(bars, d["pct_bad"], d["orders"]):
    ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}%", ha="center", fontweight="bold")
    ax.text(b.get_x() + b.get_width() / 2, 2, f"n={n:,}", ha="center", color="white", fontsize=9)
ax.set_ylabel("Orders with a 1-2 star review (%)")
ax.set_ylim(0, 95)
ax.set_title("A late delivery makes a bad review 7x more likely (62% vs 9%)")
save(fig, "01_bad_reviews_by_delivery.png", "Delivered orders with a review, Jan 2017 - Aug 2018. Late = delivered after the promised date.")

# 2. Late rate by month -------------------------------------------------------------------------
m = q("""SELECT order_month, ROUND(100.0 * AVG(is_late::int), 1) AS pct_late, COUNT(*) AS delivered
         FROM stg.orders WHERE is_delivered AND in_analysis_window GROUP BY 1 ORDER BY 1""")
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.plot(m["order_month"], m["pct_late"], color=BLUE, marker="o")
for _, r in m[m["pct_late"] >= 12].iterrows():
    ax.annotate(f"{r['pct_late']:.0f}%", (r["order_month"], r["pct_late"]), textcoords="offset points",
                xytext=(0, 8), ha="center", color=RED, fontweight="bold")
ax.set_ylabel("Delivered orders that were late (%)")
ax.set_title("Lateness is not constant: two spikes, Nov 2017 and Feb-Mar 2018")
save(fig, "02_late_rate_by_month.png", "Share of delivered orders delivered after the promised date, by purchase month.")

# 3. Feb-Mar 2018 spike by state ----------------------------------------------------------------
s = q("""SELECT c.state,
                ROUND(100.0 * AVG(o.is_late::int) FILTER (WHERE o.order_month IN ('2018-02-01','2018-03-01')), 1) AS spike,
                ROUND(100.0 * AVG(o.is_late::int) FILTER (WHERE o.order_month >= '2018-04-01'), 1) AS normal
         FROM stg.orders o JOIN stg.customers c USING (customer_id)
         WHERE o.is_delivered AND o.order_month >= '2018-02-01' AND c.state IN ('RJ','MG','SP','ES','BA','PR','RS','SC')
         GROUP BY 1 ORDER BY 2 DESC""")
fig, ax = plt.subplots(figsize=(8.5, 4.6))
x = range(len(s))
ax.bar([i - 0.2 for i in x], s["spike"], width=0.4, color=RED, label="Feb-Mar 2018")
ax.bar([i + 0.2 for i in x], s["normal"], width=0.4, color=GREY, label="Apr-Aug 2018")
ax.set_xticks(list(x))
ax.set_xticklabels(s["state"])
for i, v in zip(x, s["spike"]):
    ax.text(i - 0.2, v + 0.8, f"{v:.0f}%", ha="center", fontsize=9, fontweight="bold")
ax.set_ylabel("Delivered orders that were late (%)")
ax.set_title("Feb-Mar 2018: lateness jumped in almost every state, worst in Rio (34%)")
ax.legend(frameon=False)
save(fig, "03_spike_by_state.png", "Customer state, delivered orders. The cause is not in the data. Hypothesis to verify: a network-wide carrier or carnival disruption.")

# 4. Repeat purchase with confidence intervals -----------------------------------------------------
r = q("""WITH first AS (SELECT DISTINCT ON (customer_unique_id) customer_unique_id, order_id, purchase_ts, is_late
                       FROM stg.orders WHERE order_status <> 'canceled' ORDER BY customer_unique_id, purchase_ts)
         SELECT f.is_late, COUNT(*) AS people,
                SUM(EXISTS (SELECT 1 FROM stg.orders x WHERE x.customer_unique_id = f.customer_unique_id
                  AND x.order_status <> 'canceled' AND x.purchase_ts::date > f.purchase_ts::date
                  AND x.purchase_ts <= f.purchase_ts + INTERVAL '180 days')::int) AS repeaters
         FROM first f JOIN stg.orders o ON o.order_id = f.order_id AND o.is_delivered
         WHERE f.purchase_ts >= '2017-01-01' AND f.purchase_ts < '2018-03-01' GROUP BY 1 ORDER BY 1""")
rate = r["repeaters"] / r["people"] * 100
err = 1.96 * (rate / 100 * (1 - rate / 100) / r["people"]).apply(math.sqrt) * 100
fig, ax = plt.subplots(figsize=(7, 4.6))
ax.bar(["First order\non time", "First order\nlate"], rate, yerr=err, color=[BLUE, RED], capsize=8, width=0.5)
for i, (v, n) in enumerate(zip(rate, r["people"])):
    ax.text(i, v + err.iloc[i] + 0.15, f"{v:.2f}%", ha="center", fontweight="bold")
    ax.text(i, 0.1, f"n={n:,}", ha="center", color="white", fontsize=9)
ax.set_ylim(0, 3.2)
ax.set_ylabel("Customers who ordered again within 180 days (%)")
ax.set_title("Almost nobody reorders, on time or late (about 2%)")
save(fig, "04_repeat_purchase.png", "Error bars: 95% confidence interval. Gap not statistically significant (p = 0.08). First orders Jan 2017 - Feb 2018, so everyone had 180 days.")

# 5. Money tied up in orders that never arrived ----------------------------------------------------
f = q("""SELECT o.order_status AS status, ROUND(SUM(p.paid)::numeric / 1000, 0) AS paid_k, COUNT(*) AS orders
         FROM stg.orders o JOIN (SELECT order_id, SUM(payment_value) AS paid FROM stg.order_payments GROUP BY 1) p USING (order_id)
         WHERE NOT o.is_delivered AND o.in_analysis_window AND o.order_status IN ('shipped','unavailable','canceled','processing','invoiced')
         GROUP BY 1 ORDER BY 2 DESC""")
labels = {"shipped": "Shipped, never arrived", "unavailable": "Marked unavailable\n(paid, no item)", "canceled": "Canceled",
          "processing": "Stuck processing", "invoiced": "Stuck invoiced"}
fig, ax = plt.subplots(figsize=(8.5, 4.6))
bars = ax.barh([labels[x] for x in f["status"]][::-1], f["paid_k"][::-1], color=RED)
for b, v, n in zip(bars, f["paid_k"][::-1], f["orders"][::-1]):
    ax.text(v + 3, b.get_y() + b.get_height() / 2, f"BRL {v:,.0f}k  ({n:,} orders)", va="center")
ax.set_xlim(0, f["paid_k"].max() * 1.45)
ax.set_xlabel("Customer payments (BRL thousands)")
ax.set_title(f"BRL {f['paid_k'].sum():,.0f}k was paid for orders that were never delivered")
save(fig, "05_money_in_undelivered_orders.png", "Payments recorded on orders that were not delivered, Jan 2017 - Aug 2018. Refunds are not in the data, so this is money at risk, not confirmed loss.")

# 6. On-time orders still get bad reviews in some categories ---------------------------------------
c = q("""SELECT p.category, COUNT(DISTINCT o.order_id) AS orders, ROUND(100.0 * AVG((r.review_score <= 2)::int), 1) AS pct_bad
         FROM stg.orders o JOIN stg.reviews r USING (order_id) JOIN stg.order_items i USING (order_id)
         JOIN stg.products p USING (product_id)
         WHERE o.is_delivered AND o.in_analysis_window AND NOT o.is_late
         GROUP BY 1 HAVING COUNT(DISTINCT o.order_id) >= 800 ORDER BY 3 DESC LIMIT 8""")
fig, ax = plt.subplots(figsize=(8.5, 4.6))
bars = ax.barh(c["category"][::-1], c["pct_bad"][::-1], color=[RED if v > 14 else BLUE for v in c["pct_bad"][::-1]])
ax.axvline(9.2, color="#333333", linestyle="--")
ax.text(9.4, -0.65, "average for all on-time orders: 9%", fontsize=9)
for b, v in zip(bars, c["pct_bad"][::-1]):
    ax.text(v + 0.3, b.get_y() + b.get_height() / 2, f"{v:.0f}%", va="center", fontweight="bold")
ax.set_xlabel("On-time orders with a 1-2 star review (%)")
ax.set_title("Even on time, office furniture gets 22% bad reviews")
save(fig, "06_bad_reviews_on_time_by_category.png", "Delivered on time, categories with 800+ orders. Lateness cannot explain this; the review-text analysis (step 6) looks for the reasons.")
