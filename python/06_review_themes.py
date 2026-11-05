"""Step 6: what are unhappy customers actually writing?

1) Keyword map over EVERY review with text (no API, no quota).
2) Gemini on a 120-row stratified sample (about 8 calls). If quota is gone, keywords still stand.
3) Compare keyword vs LLM on that sample. A person then checks 40 of them.

Run:  python -u python/06_review_themes.py
      python -u python/06_review_themes.py --keywords-only
"""
import json
import re
import sys
import textwrap
import time
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy import text

from db import PROJECT_ROOT, get_engine
from llm import ask_llm, last_failure, llm_available

OUT = PROJECT_ROOT / "assets" / "eda"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE_PATH = PROJECT_ROOT / "docs" / "theme_sample.csv"
N_SAMPLE = 120
BATCH = 15

THEMES = [
    "never_arrived",
    "late_or_slow",
    "damaged_or_wrong",
    "assembly",
    "quality",
    "customer_service",
    "praise",
    "other",
]
LABEL = {
    "never_arrived": "Never arrived",
    "late_or_slow": "Late / slow",
    "damaged_or_wrong": "Damaged or wrong item",
    "assembly": "Assembly / missing parts",
    "quality": "Product quality",
    "customer_service": "Customer service",
    "praise": "Praise",
    "other": "Other / unclear",
}
# First match wins. Accents are stripped before matching.
PATTERNS = [
    ("never_arrived", r"nao recebi(?! a resposta| resposta| retorno)|nao chegou|nao veio|nao foi entregue|nunca chegou"),
    ("late_or_slow", r"atraso|atrasou|atrasad|demora|demorou|demorad|fora do prazo|passou do prazo|prazo de entrega|entrega atras"),
    ("damaged_or_wrong", r"quebrado|estragad|avaria|defeito|errado|faltando|incompleto|veio errad|produto errad|diferente do|amassado|rasgad|danific|faltou"),
    ("assembly", r"montar|montagem|parafuso|instru"),
    ("quality", r"qualidade|nao funciona|nao liga|pessimo|ruim|fragil|nao vale|nao e o mesmo|nao corresponde"),
    ("customer_service", r"atendimento|suporte|\bsac\b"),
    ("praise", r"otimo|otima|excelente|recomendo|adorei|perfeito|dentro do prazo|chegou antes|muito bom|satisfeit"),
]

SYSTEM = """You classify Brazilian Portuguese customer-review comments.
Pick EXACTLY one theme per review from this list:
never_arrived, late_or_slow, damaged_or_wrong, assembly, quality, customer_service, praise, other
Rules:
- never_arrived = customer says they did not receive the product
- late_or_slow = received (or still waiting) but complains about delay / missed promise
- damaged_or_wrong = broken, damaged, missing pieces, or the wrong item
- assembly = furniture/product hard to assemble or instructions/screws missing
- quality = product is poor, not as described, stopped working (not about delivery)
- customer_service = complaint is about the seller/platform response
- praise = positive comment
- other = none of the above
If two apply, pick the one the customer is MOST upset about.
Return ONLY a JSON array: [{"i": 1, "theme": "late_or_slow"}, ...]
"""

plt.rcParams.update({
    "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def fold(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


COMPILED = [(theme, re.compile(pat)) for theme, pat in PATTERNS]


def keyword_theme(comment):
    text_fold = fold(comment)
    for theme, rx in COMPILED:
        if rx.search(text_fold):
            return theme
    return "other"


def save(fig, name, footnote):
    wrapped = textwrap.fill(footnote, width=int(fig.get_figwidth() * 13))
    fig.text(0.01, 0.005, wrapped, fontsize=8.5, color="#555555", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03 + 0.025 * wrapped.count("\n"), 1, 1))
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("saved", name, flush=True)


def parse_json_array(raw):
    if not raw:
        return None
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return data


engine = get_engine()
print("loading reviews with text ...", flush=True)
df = pd.read_sql(text("""
SELECT r.order_id,
       r.review_score,
       r.comment_text,
       o.is_late,
       o.is_delivered,
       (SELECT p.category FROM stg.order_items i
          JOIN stg.products p USING (product_id)
         WHERE i.order_id = o.order_id
         ORDER BY i.price DESC LIMIT 1) AS category
FROM stg.reviews r
JOIN stg.orders o USING (order_id)
WHERE o.in_analysis_window AND r.has_comment
"""), engine)
df["is_late"] = df["is_late"].fillna(False).astype(bool)
df["is_delivered"] = df["is_delivered"].astype(bool)
df["is_bad"] = df["review_score"] <= 2
df["theme"] = df["comment_text"].map(keyword_theme)
print(f"  {len(df):,} comments tagged", flush=True)

bad = df[df["is_bad"]].copy()
delivered_bad = bad[bad["is_delivered"]].copy()
delivered_bad["delivery"] = np.where(delivered_bad["is_late"], "Late", "On time")

print("\n-- Keyword themes among BAD reviews with text (delivered)", flush=True)
tab = (delivered_bad.groupby(["delivery", "theme"]).size()
       .unstack(fill_value=0).reindex(columns=THEMES, fill_value=0))
pct = tab.div(tab.sum(axis=1), axis=0) * 100
print((pct.round(1)).to_string(), flush=True)
print("\ncounts:", tab.sum(axis=1).to_dict(), flush=True)

furn = delivered_bad[(delivered_bad["category"] == "office_furniture") & (delivered_bad["delivery"] == "On time")]
print(f"\n-- On-time office furniture, bad + text (n={len(furn)})", flush=True)
print((furn["theme"].value_counts(normalize=True) * 100).round(1).to_string(), flush=True)

# ---- charts
order_themes = ["never_arrived", "late_or_slow", "damaged_or_wrong", "quality", "assembly", "customer_service", "other"]
fig, ax = plt.subplots(figsize=(9.4, 5.5))
x = np.arange(len(order_themes))
w = 0.38
late_vals = [pct.loc["Late", t] if "Late" in pct.index else 0 for t in order_themes]
ontime_vals = [pct.loc["On time", t] if "On time" in pct.index else 0 for t in order_themes]
ax.bar(x - w / 2, late_vals, w, color="#c0392b", label="Late orders")
ax.bar(x + w / 2, ontime_vals, w, color="#2f6db5", label="On-time orders")
ax.set_xticks(x)
ax.set_xticklabels([LABEL[t] for t in order_themes], rotation=25, ha="right")
ax.set_ylabel("% of bad reviews that have text")
ax.legend(frameon=False)
ax.set_title("Late orders complain about delay. On-time orders complain about the product.")
save(fig, "12_review_themes_late_vs_ontime.png",
     "Keyword map on every 1-2 star review with text, Jan 2017-Aug 2018. First matching theme wins. Portuguese accents are ignored so 'nao recebi' and 'não recebi' count as the same.")

if len(furn) >= 30:
    furn_pct = (furn["theme"].value_counts(normalize=True) * 100).reindex(order_themes).fillna(0)
    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    ax.barh([LABEL[t] for t in order_themes][::-1], furn_pct.values[::-1], color="#2f6db5")
    ax.set_xlabel("% of on-time, 1-2 star office-furniture reviews with text")
    ax.set_title("On-time office furniture: the complaint is the product, not the courier.")
    save(fig, "13_office_furniture_themes.png",
         f"n={len(furn)} on-time office-furniture orders with a 1-2 star written review. This is the EDA leftover: even when on time, this category is unusually unhappy.")

# ---- LLM sample
if "--keywords-only" in sys.argv:
    print("\n--keywords-only: skipping Gemini.", flush=True)
    raise SystemExit(0)

rng = np.random.RandomState(42)

def take(frame, n):
    n = min(n, len(frame))
    if n == 0:
        return frame.iloc[0:0]
    return frame.sample(n, random_state=rng)

late_bad = delivered_bad[delivered_bad["delivery"] == "Late"]
ontime_bad = delivered_bad[(delivered_bad["delivery"] == "On time") & (delivered_bad["category"] != "office_furniture")]
furn_bad = delivered_bad[(delivered_bad["delivery"] == "On time") & (delivered_bad["category"] == "office_furniture")]
good = df[(df["review_score"] >= 5) & df["is_delivered"] & ~df["is_late"]]

sample = pd.concat([
    take(late_bad, 40),
    take(ontime_bad, 40),
    take(furn_bad, 25),
    take(good, 15),
], ignore_index=True)
sample = sample.drop_duplicates("order_id").reset_index(drop=True)
print(f"\nLLM sample size: {len(sample)}  (llm available: {llm_available()})", flush=True)

sample["llm_theme"] = pd.NA
if llm_available():
    for start in range(0, len(sample), BATCH):
        chunk = sample.iloc[start:start + BATCH]
        lines = []
        for j, row in enumerate(chunk.itertuples(), start=1):
            comment = str(row.comment_text).replace("\n", " ").strip()[:400]
            lines.append(f"{j}. {comment}")
        user = "Classify each review:\n" + "\n".join(lines)
        raw = ask_llm(SYSTEM, user)
        parsed = parse_json_array(raw)
        if not parsed:
            print(f"  batch {start}: parse failed ({last_failure['reason']})", flush=True)
            if last_failure["reason"] == "HTTP 429":
                print("  quota hit — stopping Gemini, keywords still stand.", flush=True)
                break
            continue
        by_i = {int(item.get("i")): item.get("theme") for item in parsed if "i" in item}
        for j, idx in enumerate(chunk.index, start=1):
            theme = by_i.get(j)
            if theme in THEMES:
                sample.at[idx, "llm_theme"] = theme
        tagged = sample["llm_theme"].notna().sum()
        print(f"  batch {start}-{start+len(chunk)-1}: {tagged} tagged so far", flush=True)
        time.sleep(1.5)
else:
    print("  no LLM key — sample kept with keyword themes only.", flush=True)

keep = sample[["order_id", "review_score", "is_late", "category", "comment_text", "theme"]].copy()
keep = keep.rename(columns={"theme": "keyword_theme"})
keep["llm_theme"] = sample["llm_theme"]
keep["comment_text"] = keep["comment_text"].str.replace(r"\s+", " ", regex=True).str.slice(0, 400)
keep.to_csv(SAMPLE_PATH, index=False, encoding="utf-8")
print("wrote", SAMPLE_PATH.name, flush=True)

both = keep.dropna(subset=["llm_theme"])
if len(both):
    agree = (both["keyword_theme"] == both["llm_theme"]).mean()
    print(f"\n-- Keyword vs LLM agreement on {len(both)} tagged rows: {agree:.0%}", flush=True)
    print(pd.crosstab(both["keyword_theme"], both["llm_theme"], margins=True).to_string(), flush=True)
    print("\n-- 40 rows for a person to check (print below)", flush=True)
    check = both.sample(min(40, len(both)), random_state=1)
    for i, row in enumerate(check.itertuples(), start=1):
        print(f"\n#{i} score={row.review_score} late={row.is_late} kw={row.keyword_theme} llm={row.llm_theme}", flush=True)
        print(f"   {row.comment_text[:280]}", flush=True)
