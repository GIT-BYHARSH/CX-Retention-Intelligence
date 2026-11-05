"""Step 5: can we flag a 1-2 star review at the moment the order is placed?

Honest model = only facts known at purchase (promise length, seller history up to
this order, distance, basket, payment). Delivery outcome is held out.

Oracle model = the same features PLUS is_late. That is cheating. It shows the
ceiling: how well we could do if we already knew the parcel would be late.

Split is by time, not random: train = Jan 2017-Apr 2018, test = May-Aug 2018.
Run:  python -u python/05_predict_bad_review.py
"""
import sys
import textwrap
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text

from db import PROJECT_ROOT, get_engine
from run_sql import run_file

warnings.filterwarnings("ignore", category=FutureWarning)

OUT = PROJECT_ROOT / "assets" / "eda"
OUT.mkdir(parents=True, exist_ok=True)
CUTOFF = pd.Timestamp("2018-05-01")
FLAG_SHARE = 0.20  # operations: extra care on the riskiest 20% of orders

NUMERIC = [
    "promised_days", "shipping_limit_days", "purchase_hour", "weekday", "month_num",
    "n_items", "n_sellers", "order_value", "freight_share", "installments",
    "weight_g", "photos_qty", "distance_km",
    "seller_prior_orders", "seller_prior_late_rate", "seller_prior_bad_rate",
    "customer_prior_orders",
]
BINARY = ["same_state", "is_office_furniture"]
CATEGORICAL = ["payment_type", "customer_state", "category"]
HONEST = NUMERIC + BINARY + CATEGORICAL
ORACLE_EXTRA = ["is_late"]

plt.rcParams.update({
    "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def save(fig, name, footnote):
    wrapped = textwrap.fill(footnote, width=int(fig.get_figwidth() * 13))
    fig.text(0.01, 0.005, wrapped, fontsize=8.5, color="#555555", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03 + 0.025 * wrapped.count("\n"), 1, 1))
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("saved", name, flush=True)


def clip_odds(df):
    df = df.copy()
    df["promised_days"] = df["promised_days"].clip(0, 60)
    df["shipping_limit_days"] = df["shipping_limit_days"].clip(0, 30)
    df["distance_km"] = df["distance_km"].clip(0, 4000)
    df["order_value"] = df["order_value"].clip(0, 5000)
    df["is_late"] = df["is_late"].astype(int)
    df["same_state"] = df["same_state"].astype(int)
    df["is_office_furniture"] = df["is_office_furniture"].astype(int)
    df["is_bad_review"] = df["is_bad_review"].astype(int)
    return df


def make_pipe(feature_names):
    num = [c for c in feature_names if c in NUMERIC + BINARY + ORACLE_EXTRA]
    cat = [c for c in feature_names if c in CATEGORICAL]
    pre = ColumnTransformer([
        ("num", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), num),
        ("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=0.02)),
        ]), cat),
    ])
    return Pipeline([
        ("pre", pre),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=1000, solver="lbfgs")),
    ])


def flag_metrics(y, proba, share=FLAG_SHARE):
    """Treat the top `share` of scores as flagged. Returns precision, recall, n_flagged."""
    n = len(y)
    k = max(1, int(round(n * share)))
    order = np.argsort(-proba)
    picked = np.zeros(n, dtype=bool)
    picked[order[:k]] = True
    tp = int((picked & (y == 1)).sum())
    flagged = int(picked.sum())
    actual_bad = int((y == 1).sum())
    precision = tp / flagged if flagged else 0.0
    recall = tp / actual_bad if actual_bad else 0.0
    return {"flagged": flagged, "tp": tp, "precision": precision, "recall": recall}


def rule_score(df):
    """Simple rule a manager could write on a whiteboard. Higher = riskier."""
    late = df["seller_prior_late_rate"].fillna(0)
    bad = df["seller_prior_bad_rate"].fillna(0)
    return (
        3.0 * late
        + 2.0 * bad
        + 0.5 * (df["promised_days"] < 8).astype(float)
        + 0.8 * df["is_office_furniture"]
        + 0.3 * (df["n_sellers"] > 1).astype(float)
        + 0.2 * (1 - df["same_state"])
    )


if "--skip-sql" not in sys.argv:
    print("building dw.model_orders ...", flush=True)
    run_file("sql/05_model_features.sql")

engine = get_engine()
raw = pd.read_sql(text("SELECT * FROM dw.model_orders"), engine)
raw = clip_odds(raw)
raw["purchase_ts"] = pd.to_datetime(raw["purchase_ts"])
train = raw[raw["purchase_ts"] < CUTOFF].copy()
test = raw[raw["purchase_ts"] >= CUTOFF].copy()
y_tr, y_te = train["is_bad_review"].values, test["is_bad_review"].values
base_te = y_te.mean()

print("\n-- Rows", flush=True)
print(f"  labeled orders (delivered + reviewed, Jan 2017-Aug 2018): {len(raw):,}")
print(f"  train (< {CUTOFF.date()}): {len(train):,}   bad-review rate {y_tr.mean():.1%}")
print(f"  test  (>= {CUTOFF.date()}): {len(test):,}   bad-review rate {base_te:.1%}")

# --- models
honest = make_pipe(HONEST).fit(train[HONEST], y_tr)
oracle = make_pipe(HONEST + ORACLE_EXTRA).fit(train[HONEST + ORACLE_EXTRA], y_tr)
p_honest = honest.predict_proba(test[HONEST])[:, 1]
p_oracle = oracle.predict_proba(test[HONEST + ORACLE_EXTRA])[:, 1]
p_rule = rule_score(test).values
p_dummy = np.full(len(test), y_tr.mean())

print("\n-- Ranking quality on the test months (May-Aug 2018)", flush=True)
print(f"  {'model':<28} {'ROC-AUC':>8} {'PR-AUC':>8}  (PR-AUC chance = {base_te:.3f})")
for name, p in [
    ("always guess the average", p_dummy),
    ("whiteboard rule", p_rule),
    ("honest logistic (purchase)", p_honest),
    ("oracle logistic (+ is_late)", p_oracle),
]:
    print(f"  {name:<28} {roc_auc_score(y_te, p):8.3f} {average_precision_score(y_te, p):8.3f}")

print(f"\n-- If ops extra-cares the riskiest {FLAG_SHARE:.0%} of test orders", flush=True)
print(f"  {'model':<28} {'precision':>10} {'recall':>8} {'lift vs base':>12}")
rows_m = []
for name, p in [
    ("random {0:.0%} of orders".format(FLAG_SHARE), np.random.RandomState(0).rand(len(test))),
    ("whiteboard rule", p_rule),
    ("honest logistic", p_honest),
    ("oracle (+ is_late)", p_oracle),
]:
    m = flag_metrics(y_te, p)
    m["name"] = name
    m["lift"] = m["precision"] / base_te if base_te else 0
    rows_m.append(m)
    print(f"  {name:<28} {m['precision']:10.1%} {m['recall']:8.1%} {m['lift']:11.2f}x")

h, o_ = rows_m[2], rows_m[3]

# coefficients of the honest model (standardised units)
pre = honest.named_steps["pre"]
clf = honest.named_steps["clf"]
feat_names = pre.get_feature_names_out()
coef = pd.Series(clf.coef_[0], index=feat_names).sort_values()
top = pd.concat([coef.head(8), coef.tail(8)])

print("\n-- Honest model: strongest signals (std units, + means more likely a bad review)", flush=True)
print(top.round(3).to_string(), flush=True)
print("\n-- Named features of interest", flush=True)
for k in ["num__promised_days", "num__seller_prior_late_rate", "num__seller_prior_bad_rate",
          "num__distance_km", "num__is_office_furniture", "num__freight_share",
          "num__n_items", "num__n_sellers", "num__same_state"]:
    print(f"  {k.replace('num__',''):<28} {coef.get(k, float('nan')):7.3f}", flush=True)

print("\n-- Leakage check: oracle should beat honest. If it does not, is_late is unused.", flush=True)
print(f"  honest ROC-AUC {roc_auc_score(y_te, p_honest):.3f} vs oracle {roc_auc_score(y_te, p_oracle):.3f}",
      flush=True)

# ---------------------------------------------------------------- charts
# 1. precision-recall
fig, ax = plt.subplots(figsize=(9.2, 5.5))
for label, p, color in [
    (f"Honest purchase-time model  (PR-AUC {average_precision_score(y_te, p_honest):.2f})", p_honest, "#2f6db5"),
    (f"Oracle that already knows lateness  (PR-AUC {average_precision_score(y_te, p_oracle):.2f})", p_oracle, "#c0392b"),
]:
    prec, rec, _ = precision_recall_curve(y_te, p)
    ax.plot(rec, prec, color=color, label=label)
ax.axhline(base_te, color="#9aa5b1", linestyle="--", label=f"Chance (bad-review rate {base_te:.0%})")
ax.set_xlabel("Recall (share of all bad reviews we catch)")
ax.set_ylabel("Precision (share of flagged orders that really are bad)")
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.legend(frameon=False, loc="upper right")
ax.set_title(f"Flag the riskiest 20% at checkout: catch {h['recall']:.0%} of bad reviews")
save(fig, "09_model_pr_curve.png",
     "Test set May-Aug 2018. Honest features are known at checkout. Oracle adds is_late, which is not known until the parcel arrives. Chance is a flat line at the 10% base rate.")

# 2. coefficients
fig, ax = plt.subplots(figsize=(9, 6.0))
colors = ["#c0392b" if v > 0 else "#2f6db5" for v in top.values]
ax.barh(range(len(top)), top.values, color=colors)
ax.set_yticks(range(len(top)))
pretty = [n.replace("num__", "").replace("cat__", "").replace("infrequent_sklearn", "other") for n in top.index]
ax.set_yticklabels(pretty)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_xlabel("Effect on log-odds of a 1-2 star review (after scaling)")
ax.set_title("Rio is the strongest purchase-time risk. Same-state orders are safer.")
save(fig, "10_model_coefficients.png",
     "Logistic regression on purchase-time features. Bars to the right mean a worse review is more likely. Seller history uses only earlier orders, so there is no future leak.")

# 3. lift bars
fig, ax = plt.subplots(figsize=(9.2, 5.4))
labels = ["Any 20%\n(random)", "Whiteboard\nrule", "Honest model\n(purchase time)", "Oracle\n(+ lateness)"]
vals = [rows_m[0]["precision"] * 100, rows_m[1]["precision"] * 100,
        rows_m[2]["precision"] * 100, rows_m[3]["precision"] * 100]
bar_colors = ["#9aa5b1", "#7f8c8d", "#2f6db5", "#c0392b"]
bars = ax.bar(labels, vals, color=bar_colors)
ax.axhline(base_te * 100, color="#555555", linestyle="--", linewidth=1, label=f"base rate {base_te:.0%}")
ax.set_ylim(0, max(vals) * 1.22)
for b, v, r in zip(bars, vals, rows_m):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}%\nrecall {r['recall']:.0%}",
            ha="center", va="bottom", fontsize=9)
ax.set_ylabel("% of the flagged 20% that actually got 1-2 stars")
ax.set_title(f"Checkout score is {h['lift']:.1f}x random. Knowing lateness is {o_['lift']:.1f}x.")
ax.legend(frameon=False, loc="upper left")
save(fig, "11_model_lift.png",
     "Same test months. Random 20% uses shuffled scores so it matches the base rate. The gap between honest and oracle is the value of watching deliveries, not of a smarter checkout score.")

print("\nDone. Charts 09-11 in assets/eda/", flush=True)
