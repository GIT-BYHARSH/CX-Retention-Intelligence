"""Charts for the cohort table and the RFM segments. Titles state the takeaway.
Run:  python -u python/04b_cohort_rfm_charts.py
"""
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy import text

from db import PROJECT_ROOT, get_engine

OUT = PROJECT_ROOT / "assets" / "eda"
OUT.mkdir(parents=True, exist_ok=True)
engine = get_engine()

plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def save(fig, name, footnote):
    wrapped = textwrap.fill(footnote, width=int(fig.get_figwidth() * 13))
    fig.text(0.01, 0.005, wrapped, fontsize=8.5, color="#555555", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03 + 0.025 * wrapped.count("\n"), 1, 1))
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("saved", name, flush=True)


cohort = pd.read_sql("""
SELECT to_char(first_month, 'YYYY-MM') AS first_month, months_since_first, pct_active
FROM dw.report_cohort""", engine)
wide = cohort.pivot(index="first_month", columns="months_since_first", values="pct_active")
# month 0 is always 100 and would wash out the colour scale; show months 1-6
heat = wide[[c for c in wide.columns if c > 0]].values.astype(float)

fig, ax = plt.subplots(figsize=(9, 6.2))
im = ax.imshow(heat, cmap="YlOrRd", aspect="auto", vmin=0, vmax=0.8)
ax.set_yticks(range(len(wide.index)))
ax.set_yticklabels(wide.index)
ax.set_xticks(range(heat.shape[1]))
ax.set_xticklabels([f"M+{int(c)}" for c in wide.columns if c > 0])
for i in range(heat.shape[0]):
    for j in range(heat.shape[1]):
        ax.text(j, i, f"{heat[i, j]:.2f}", ha="center", va="center", fontsize=8,
                color="white" if heat[i, j] > 0.45 else "black")
ax.set_xlabel("Months after the first order")
ax.set_title("Every cohort drops below 1% by the next month. Loyalty is not the business.")
fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="% of the cohort with an order that month")
save(fig, "07_cohort_retention.png",
     "People whose first order was in that month. A later-calendar-day order counts. Cohorts run to Feb 2018 so each has 6 months of follow-up.")

rfm = pd.read_sql("SELECT segment, people, pct_people, pct_spend FROM dw.report_rfm_summary ORDER BY segment DESC", engine)
short = rfm["segment"].str.replace(r"^\d+ ", "", regex=True)
fig, ax = plt.subplots(figsize=(9.5, 5.6))
y = np.arange(len(rfm))
ax.barh(y - 0.18, rfm["pct_people"], height=0.35, color="#9aa5b1", label="% of people")
ax.barh(y + 0.18, rfm["pct_spend"], height=0.35, color="#2f6db5", label="% of spend")
ax.set_yticks(y)
ax.set_yticklabels(short)
ax.legend(frameon=False, loc="upper right")
ax.set_xlim(0, 52)
ax.set_xlabel("Share of customers / share of revenue (%)")
ax.set_title("Save recent high-value first-timers: 16% of people, 29% of spend")
save(fig, "08_rfm_segments.png",
     "Snapshot 31 Aug 2018. Frequency is scored from the real order count, not quintiles (97% of people have one order, so quintiles would be random).")
