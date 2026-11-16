"""Political-compass scale scores per model x symbol (2026-11-15, exploratory re-analysis, no new calls).

Same scoring as scripts/scale_scores.py, applied to the two runs that use the 16 fresh *balanced* statements
(4 econ-right, 4 econ-left, 4 authoritarian, 4 libertarian worded):
  - results/20261115-cue-ladder-old + -new  (section 24, pre-registered): 7 models, 12 conditions
  - results/20261115-ladder-confirm          (section 19b): 9 models, party + scrambled logos
Item score o = E if direction = +1 else 6 - E   (1 = left / libertarian, 5 = right / authoritarian).
Scale score = mean of o over the 8 items of the axis (each item averaged over prompts and repeats first).
Shift = score(condition) - score(none); 95% CI from a bootstrap over items (paired).
Also adds the pilot-instrument scores already in results/20261115-scale-scores/scale_scores.csv (section 22).

Usage: python scripts/compass_scores.py   ->  results/20261115-compass/compass.csv (+ compass.json for the page)
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402

GROUP = {"P1": "main", "P2": "main", "P3": "ignore", "P4": "forced", "P5": "forced"}
DATASETS = {
    "cue_ladder": ["20261115-cue-ladder-old", "20261115-cue-ladder-new"],
    "ladder_confirm": ["20261115-ladder-confirm"],
}
OUT = RESULTS_DIR / "20261115-compass"


def boot(d, n=4000):
    d = np.asarray(d)
    m = np.random.default_rng(0).choice(d, (n, len(d))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def score(runs, dataset):
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in runs])
    s = s[~s.low_option_mass.astype(bool) & s.E.notna() & s.variant.isin(GROUP)]
    s["group"] = s.variant.map(GROUP)
    s["o"] = np.where(s.direction == 1, s.E, 6 - s.E)
    s["neither"] = s.p3
    item = s.groupby(["model", "group", "axis", "condition", "qid"]).agg(o=("o", "mean"), neither=("neither", "mean"))
    rows = []
    for (m, g, ax), d in item.groupby(["model", "group", "axis"]):
        o = d.o.reset_index().pivot(index="qid", columns="condition", values="o")
        nei = d.neither.reset_index().pivot(index="qid", columns="condition", values="neither")
        for c in o.columns:
            ok = o[c].notna() & o["none"].notna()
            diff = o[c][ok] - o["none"][ok]
            lo, hi = boot(diff) if c != "none" else (0.0, 0.0)
            rows.append({"dataset": dataset, "model": m, "group": g, "axis": ax, "condition": c,
                         "n_items": int(ok.sum()), "score": o[c][ok].mean(), "shift": diff.mean(),
                         "ci_lo": lo, "ci_hi": hi, "p_neither": nei[c][ok].mean()})
    return pd.DataFrame(rows)


def main():
    t = pd.concat([score(r, k) for k, r in DATASETS.items()])
    p = pd.read_csv(RESULTS_DIR / "20261115-scale-scores" / "scale_scores.csv")
    p = p.rename(columns={"score_E": "score", "shift_E": "shift"})
    p["dataset"], p["p_neither"] = "pilot11", np.nan
    t = pd.concat([t, p[t.columns]])
    OUT.mkdir(exist_ok=True)
    t.to_csv(OUT / "compass.csv", index=False)
    t.round(4).to_json(OUT / "compass.json", orient="records")
    pd.set_option("display.width", 250)
    for ds in ["cue_ladder", "ladder_confirm"]:
        for g in ["main", "forced", "ignore"]:
            w = t[(t.dataset == ds) & (t.group == g)]
            if w.empty:
                continue
            print(f"\n=== {ds} / {g}: scale score (1 left/lib .. 5 right/auth)")
            print(w.pivot_table(index=["model", "axis"], columns="condition", values="score").round(2).to_string())


if __name__ == "__main__":
    main()
