"""Mixed symbols on the original 11 pilot statements (2026-11-15, exploratory).

Usage: python scripts/pilot_mixed_analysis.py
Reads results/20261115-explore-pilot-mixed{,-luna}/scores.csv. Writes pilot_mixed_tests.csv and
pilot_mixed_per_statement.csv to results/20261115-explore-pilot-mixed/ and prints the table.

Per statement, E averaged over the group's prompts and repeats. Groups: main = P1/P2, ignore = P3, forced = P4/P5.
Contrasts (negative = expected direction):
  party      (E_democrat - E_republican) * direction           (more left/libertarian with the Democrat logo)
  party_scr  same with the scrambled logos                     (colour/shape control)
  thumbs     E_thumbs_down - E_thumbs_up                       (agreement, no direction)
  stars      E_stars1 - E_stars5
  colour     E_red - E_green                                   (colour-only control)
Across the 11 statements: one-sided sign test + Wilcoxon (D < 0), bootstrap 95% CI, Holm over the 5 contrasts
within each model x group. Also reports mean |D| (size regardless of sign).
"""
import sys

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402
from vcb.primary import sign_and_wilcoxon  # noqa: E402

RUNS = ["20261115-explore-pilot-mixed", "20261115-explore-pilot-mixed-luna"]
GROUP = {"P1": "main", "P2": "main", "P3": "ignore", "P4": "forced", "P5": "forced"}
CONTRASTS = {"party": ("republican", "democrat", True), "party_scr": ("scrambled_republican", "scrambled_democrat", True),
             "thumbs": ("thumbs_up", "thumbs_down", False), "stars": ("stars5", "stars1", False),
             "colour": ("green", "red", False)}


def boot_ci(x, n=5000):
    m = np.random.default_rng(0).choice(np.asarray(x), (n, len(x))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def main():
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in RUNS])
    s = s[~s.low_option_mass.astype(bool) & s.E.notna()]
    s["group"] = s.variant.map(GROUP)
    e = s.groupby(["model", "group", "qid", "direction", "condition"]).E.mean().unstack("condition").reset_index()
    per_q, rows = [], []
    for name, (pos, neg, directional) in CONTRASTS.items():
        sign = e.direction if directional else 1
        per_q.append(e[["model", "group", "qid"]].assign(contrast=name, D=(e[neg] - e[pos]) * sign,
                                                          S_pos=(e[pos] - e["none"]) * sign,
                                                          S_neg=(e[neg] - e["none"]) * sign))
    per_q = pd.concat(per_q).dropna(subset=["D"])
    for (m, g, c), d in per_q.groupby(["model", "group", "contrast"]):
        st = sign_and_wilcoxon(d.set_index("qid").D, -1)
        lo, hi = boot_ci(d.D)
        rows.append({"model": m, "group": g, "contrast": c, "n_q": len(d), "mean_D": d.D.mean(), "ci_lo": lo,
                     "ci_hi": hi, "mean_absD": d.D.abs().mean(), "S_pos": d.S_pos.mean(), "S_neg": d.S_neg.mean(),
                     "expected_sign": f"{st['n_expected_sign']}/{st['n_nonzero']}", "sign_p": st["sign_test_p"],
                     "wilcoxon_p": st["wilcoxon_p"]})
    t = pd.DataFrame(rows)
    t["holm_p"] = t.groupby(["model", "group"]).wilcoxon_p.transform(
        lambda p: multipletests(p.fillna(1), method="holm")[1])
    t["contrast"] = pd.Categorical(t.contrast, list(CONTRASTS))
    t["group"] = pd.Categorical(t.group, ["main", "ignore", "forced"])
    t = t.sort_values(["model", "group", "contrast"])
    out = RESULTS_DIR / RUNS[0]
    t.to_csv(out / "pilot_mixed_tests.csv", index=False)
    per_q.to_csv(out / "pilot_mixed_per_statement.csv", index=False)
    pd.set_option("display.width", 220)
    print(t.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
