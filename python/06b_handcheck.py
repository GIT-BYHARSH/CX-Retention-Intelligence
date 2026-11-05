"""Step 6b: a person labelled 40 Gemini rows by reading the Portuguese.

Labels were decided from the comment, not by copying the model. Re-run:
    python -u python/06b_handcheck.py
"""
import pandas as pd

from db import PROJECT_ROOT

# Same 40 rows the main script printed (tagged rows, random_state=1), in that print order.
HUMAN = [
    "damaged_or_wrong",   # 1 missing chair piece; 'nao recebi' was about the email reply
    "never_arrived",      # 2 still has not received the product
    "quality",            # 3 rug is a placemat
    "praise",             # 4
    "praise",             # 5
    "damaged_or_wrong",   # 6 chair seat problem
    "damaged_or_wrong",   # 7 wrong toner colour
    "damaged_or_wrong",   # 8 two safes, one arrived
    "damaged_or_wrong",   # 9 six chairs, one arrived, wrong colour
    "damaged_or_wrong",   # 10 missing extra hoop
    "quality",            # 11 thin fabric (score 2) despite some praise
    "praise",             # 12
    "praise",             # 13
    "late_or_slow",       # 14 stuck at the post office, late
    "praise",             # 15 text is praise even though score is 1
    "assembly",           # 16 missing flange, cannot assemble
    "damaged_or_wrong",   # 17 box torn, missing parts
    "damaged_or_wrong",   # 18 6 cartridges, received 4
    "praise",             # 19
    "quality",            # 20 colour not as in the photo
    "damaged_or_wrong",   # 21 three chairs, all missing parts
    "praise",             # 22
    "never_arrived",      # 23 still waiting for delivery
    "never_arrived",      # 24 paid, never received
    "praise",             # 25
    "damaged_or_wrong",   # 26 late AND wrong product; product is the sharper complaint
    "praise",             # 27
    "customer_service",   # 28 cancelled, waiting for refund
    "praise",             # 29
    "late_or_slow",       # 30 past the promise date, still in transit
    "never_arrived",      # 31 shelves never arrived
    "praise",             # 32
    "quality",            # 33 not as in the photo, does not work
    "damaged_or_wrong",   # 34 arrived defective (button fell off)
    "quality",            # 35
    "late_or_slow",       # 36 had to collect from a distant post office
    "late_or_slow",       # 37 promise missed, still nothing
    "quality",            # 38 advert implied two boxes
    "damaged_or_wrong",   # 39 bought two, received one
    "praise",             # 40
]

sample = pd.read_csv(PROJECT_ROOT / "docs" / "theme_sample.csv")
both = sample.dropna(subset=["llm_theme"])
check = both.sample(min(40, len(both)), random_state=1).copy()
if len(check) != len(HUMAN):
    raise SystemExit(f"expected {len(HUMAN)} rows, got {len(check)}")
check["human_theme"] = HUMAN
check["llm_ok"] = check["llm_theme"] == check["human_theme"]
check["kw_ok"] = check["keyword_theme"] == check["human_theme"]
path = PROJECT_ROOT / "docs" / "theme_handcheck.csv"
check.to_csv(path, index=False, encoding="utf-8")
print(f"wrote {path.name}")
print(f"LLM vs person: {check['llm_ok'].mean():.0%}  ({int(check['llm_ok'].sum())}/{len(check)})")
print(f"Keywords vs person: {check['kw_ok'].mean():.0%}  ({int(check['kw_ok'].sum())}/{len(check)})")
print("\nLLM misses:")
print(check.loc[~check["llm_ok"], ["review_score", "keyword_theme", "llm_theme", "human_theme"]].to_string(index=False))
