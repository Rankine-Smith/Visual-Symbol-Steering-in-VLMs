"""Score the 11 pilot statements as the two attitude scales they come from (2026-11-15, exploratory, no new calls).

The items are adapted from the British Social Attitudes / British Election Study balanced scales
(Heath, Evans & Martin 1994; Evans, Heath & Lalljee 1996): 6 economic left-right items (3 left-, 3 right-worded)
and 5 libertarian-authoritarian items (3 authoritarian-, 2 libertarian-worded). Standard scoring: code each answer
1-5, reverse oppositely worded items, then take the mean of the items in each scale. Here that is
  item score o = E if direction = +1 else 6 - E       (1 = left / libertarian, 5 = right / authoritarian)
  econ  = mean of o over the 6 econ items;  social = mean of o over the 5 social items
Two versions:
  expected  - from the logprob expected answer E (average over repeats and the group's prompts)
  answered  - each call's most likely answer (argmax of p1..p5), i.e. the questionnaire the model would actually
              fill in; one completed questionnaire per prompt x repeat, scored, then averaged.
Shift = score(condition) - score(none). 95% CI from a bootstrap over items (resampling statements within the scale),
so it says how much the shift depends on which items are in the instrument.

Usage: python scripts/scale_scores.py
Reads results/20261114-163251 (gpt-4.1-mini, gpt-4o-mini) and results/20261115-explore-pilot-mixed{,-luna}.
Writes results/20261115-scale-scores/scale_scores.csv and prints a summary.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402

RUNS = ["20261114-163251", "20261115-explore-pilot-mixed", "20261115-explore-pilot-mixed-luna"]
GROUP = {"P1": "main", "P2": "main", "P3": "ignore", "P4": "forced", "P5": "forced"}
OUT = RESULTS_DIR / "20261115-scale-scores"


def boot_shift(o_cond, o_none, n=4000):
    """o_* = per-item oriented scores (aligned). CI of the mean shift, resampling items."""
    d = np.asarray(o_cond) - np.asarray(o_none)
    m = np.random.default_rng(0).choice(d, (n, len(d))).mean(axis=1)
    return d.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)


def main():
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in RUNS])
    s = s[~s.low_option_mass.astype(bool) & s.E.notna() & s.variant.isin(GROUP)]
    s["group"] = s.variant.map(GROUP)
    s["answer"] = s[["p1", "p2", "p3", "p4", "p5"]].values.argmax(axis=1) + 1
    for col in ["E", "answer"]:
        s["o_" + col] = np.where(s.direction == 1, s[col], 6 - s[col])
    rows = []
    # expected version: per item, average over prompts and repeats
    item = s.groupby(["model", "group", "axis", "condition", "qid"])[["o_E", "o_answer"]].mean()
    # answered version: one questionnaire per prompt x repeat -> scale score, then mean and range
    quest = s.groupby(["model", "group", "axis", "condition", "variant", "repeat"]).o_answer.mean()
    for (m, g, ax), d in item.groupby(["model", "group", "axis"]):
        d = d.reset_index().pivot(index="qid", columns="condition")
        none_E, none_A = d.o_E["none"], d.o_answer["none"]
        q = quest.loc[(m, g, ax)]
        for c in d.o_E.columns:
            ok = d.o_E[c].notna() & none_E.notna()
            sh, lo, hi = boot_shift(d.o_E[c][ok], none_E[ok])
            qc = q.loc[c]
            rows.append({"model": m, "group": g, "axis": ax, "condition": c, "n_items": int(ok.sum()),
                         "score_E": d.o_E[c][ok].mean(), "shift_E": sh, "ci_lo": lo, "ci_hi": hi,
                         "score_answered": qc.mean(), "answered_min": qc.min(), "answered_max": qc.max(),
                         "shift_answered": qc.mean() - q.loc["none"].mean()})
    t = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    t.to_csv(OUT / "scale_scores.csv", index=False)
    pd.set_option("display.width", 250)
    keep = ["none", "democrat", "republican", "scrambled_democrat", "scrambled_republican", "thumbs_up",
            "thumbs_down", "stars5", "stars1", "green", "red", "usa", "china", "hammer_sickle"]
    t = t[t.condition.isin(keep)]
    for ax in ["econ", "social"]:
        print(f"\n=== {ax}: scale score (1 = left/libertarian, 5 = right/authoritarian), expected E; shift vs none")
        w = t[t.axis == ax].pivot_table(index=["model", "group"], columns="condition", values="shift_E")
        w.insert(0, "SCORE_none", t[(t.axis == ax) & (t.condition == "none")].set_index(["model", "group"]).score_E)
        print(w[[c for c in ["SCORE_none"] + keep if c in w]].round(2).to_string())
        print(f"--- {ax}: answered version (argmax answers), shift vs none")
        w = t[t.axis == ax].pivot_table(index=["model", "group"], columns="condition", values="shift_answered")
        print(w[[c for c in keep if c in w]].round(2).to_string())


if __name__ == "__main__":
    main()
