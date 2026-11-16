"""Non-political cues on political statements (2026-11-15, exploratory).

Usage: python scripts/cues_analysis.py
Reads results/20261115-explore-cues{,-luna}/scores.csv. Writes results/20261115-explore-cues/cue_tests.csv and
cue_per_statement.csv, prints the table.

Statements are coded by agreement (direction +1). Per model x format (neutral = P1/P2, forced = P4/P5) x pair,
per statement: D = E_negative - E_positive (negative = expected: less agreement with the negative cue),
S_pos / S_neg = E_cue - E_none (+ = more agreement). E is averaged over the format's two prompts and repeats.
Across the 19 statements: one-sided sign test and Wilcoxon (expected D < 0), bootstrap 95% CI, and Holm
correction of the Wilcoxon p over the 6 pairs within each model x format.
"""
import sys

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402
from vcb.primary import sign_and_wilcoxon  # noqa: E402

RUNS = ["20261115-explore-cues", "20261115-explore-cues-luna"]
PAIRS = {"thumbs": ("thumbs_up", "thumbs_down"), "faces": ("smile", "frown"), "stars": ("stars5", "stars1"),
         "stamp": ("approved", "rejected"), "social proof": ("most_agree", "few_agree"), "colour": ("green", "red")}
FORMAT = {"P1": "neutral", "P2": "neutral", "P4": "forced", "P5": "forced"}


def boot_ci(x, n=5000):
    m = np.random.default_rng(0).choice(np.asarray(x), (n, len(x))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def main():
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in RUNS])
    s = s[~s.low_option_mass.astype(bool) & s.E.notna()]
    s["format"] = s.variant.map(FORMAT)
    e = s.groupby(["model", "format", "qid", "condition"]).E.mean().unstack("condition")
    per_q, rows = [], []
    for pair, (pos, neg) in PAIRS.items():
        d = pd.DataFrame({"D": e[neg] - e[pos], "S_pos": e[pos] - e["none"], "S_neg": e[neg] - e["none"]})
        per_q.append(d.assign(pair=pair).reset_index())
    per_q = pd.concat(per_q)
    for (model, fmt, pair), g in per_q.groupby(["model", "format", "pair"]):
        st = sign_and_wilcoxon(g.set_index("qid").D, -1)
        lo, hi = boot_ci(g.D)
        rows.append({"model": model, "format": fmt, "pair": pair, "mean_D": g.D.mean(), "ci_lo": lo, "ci_hi": hi,
                     "S_pos": g.S_pos.mean(), "S_neg": g.S_neg.mean(),
                     "expected_sign": f"{st['n_expected_sign']}/{st['n_nonzero']}",
                     "sign_p": st["sign_test_p"], "wilcoxon_p": st["wilcoxon_p"]})
    t = pd.DataFrame(rows)
    t["holm_p"] = t.groupby(["model", "format"]).wilcoxon_p.transform(
        lambda p: multipletests(p.fillna(1), method="holm")[1])
    t["pair"] = pd.Categorical(t.pair, list(PAIRS))
    t = t.sort_values(["format", "model", "pair"])
    out = RESULTS_DIR / RUNS[0]
    t.to_csv(out / "cue_tests.csv", index=False)
    per_q.to_csv(out / "cue_per_statement.csv", index=False)
    pd.set_option("display.width", 220)
    print(t.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
