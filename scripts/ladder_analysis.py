"""Model-ladder analysis (2026-11-15): Democrat vs Republican corner-logo effect per model.

Usage: python scripts/ladder_analysis.py <run_id> [<run_id> ...]
Writes results/<first run_id>/ladder.csv and prints the table.

Per model and prompt group (main = P1+P2 averaged, ignore = P3):
  D_q = (E_democrat - E_republican) * direction per statement (negative = expected: more left with Democrat)
  S_party = mean (E_party - E_none) * direction (positive = more right)
Tests across statements: one-sided sign test and Wilcoxon (expected D < 0), bootstrap 95% CI of mean D.
Screening rule (fixed before the run, see configs/ladder/screen.yaml): CANDIDATE if mean D < 0 and Wilcoxon p < 0.10.
Confirmation rule (configs/ladder/confirm.yaml): CONFIRMED if mean D < 0 and the Wilcoxon p, Holm-corrected across
the models in the run (per prompt group), is < 0.05. If the run has scrambled logos, D_scr (scrambled_democrat vs
scrambled_republican) is reported; an effect that the scrambled logos reproduce doesn't count.
E is averaged over repeats; rows with low option mass are dropped.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402
from vcb.primary import sign_and_wilcoxon  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

GROUP = {"P1": "main (P1/P2)", "P2": "main (P1/P2)", "P3": "ignore (P3)"}
ORDER = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "gpt-5.1", "gpt-5.2", "gpt-5.4-nano", "gpt-5.4-mini",
         "gpt-5.4", "gpt-5.5", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-luna", "gpt-6.1-terra",
         "gpt-6-sol"]


def boot_ci(x, n=5000, seed=0):
    x = np.asarray(x)
    m = np.random.default_rng(seed).choice(x, (n, len(x))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def main(run_ids):
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in run_ids])
    s = s[~s.low_option_mass.astype(bool) & s.E.notna() & s.variant.isin(GROUP)]
    c = s.groupby(["model", "variant", "qid", "direction", "condition"]).agg(E=("E", "mean"), p3=("p3", "mean"))
    w = c.E.unstack("condition").reset_index()
    w["D"] = (w.democrat - w.republican) * w.direction
    w["S_dem"] = (w.democrat - w.none) * w.direction
    w["S_rep"] = (w.republican - w.none) * w.direction
    has_scr = "scrambled_democrat" in w
    w["D_scr"] = (w.scrambled_democrat - w.scrambled_republican) * w.direction if has_scr else np.nan
    w["group"] = w.variant.map(GROUP)
    neu = c.p3.groupby(["model", "variant"]).mean().unstack("variant")
    per_q = w.groupby(["model", "group", "qid"])[["D", "S_dem", "S_rep", "D_scr"]].mean().reset_index()
    rows = []
    for (m, g), d in per_q.groupby(["model", "group"]):
        st = sign_and_wilcoxon(d.set_index("qid").D, -1)
        lo, hi = boot_ci(d.D)
        rows.append({"model": m, "group": g, "n_q": len(d), "mean_D": d.D.mean(), "ci_lo": lo, "ci_hi": hi,
                     "S_dem": d.S_dem.mean(), "S_rep": d.S_rep.mean(), "D_scrambled": d.D_scr.mean(),
                     "expected_sign": f"{st['n_expected_sign']}/{st['n_nonzero']}",
                     "sign_p": st["sign_test_p"], "wilcoxon_p": st["wilcoxon_p"],
                     "p_neither": neu.loc[m, "P1" if g.startswith("main") else "P3"],
                     "candidate": bool(d.D.mean() < 0 and st["wilcoxon_p"] < 0.10)})
    out = pd.DataFrame(rows)
    out["holm_p"] = out.groupby("group").wilcoxon_p.transform(lambda p: multipletests(p.fillna(1), method="holm")[1])
    out["confirmed"] = (out.mean_D < 0) & (out.holm_p < 0.05)
    out["rank"] = out.model.map({m: i for i, m in enumerate(ORDER)})
    out = out.sort_values(["group", "rank"]).drop(columns="rank")
    out.to_csv(RESULTS_DIR / run_ids[0] / "ladder.csv", index=False)
    per_q.to_csv(RESULTS_DIR / run_ids[0] / "ladder_per_statement.csv", index=False)
    pd.set_option("display.width", 220)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:])
