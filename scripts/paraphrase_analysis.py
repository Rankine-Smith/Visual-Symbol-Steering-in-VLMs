"""Exp D (2026-11-15 evening, exploratory): paraphrase noise floor vs the party-logo effect.

Usage: python scripts/paraphrase_analysis.py
Reads results/20261115-explore-paraphrase/scores.csv (P1, PA, PB, PC; none/democrat/republican; 16 ladder statements;
gpt-4.1-mini, gpt-4.1; 1 repeat) and, for the option-order floor, results/20261115-ladder-confirm (P1 vs P2, repeat 0).
Free. Writes results/20261115-explore-paraphrase/{paraphrase.csv, summary.md}.
  paraphrase floor = mean over statements of |E_Px(none) - E_P1(none)|
  party shift size = mean |E_logo - E_none| (same prompt), for comparison
  party D = (E_dem - E_rep) * direction per statement; one-sided Wilcoxon (expected < 0)
"""
import sys

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402

RUN = RESULTS_DIR / "20261115-explore-paraphrase"


def load(run, variants):
    s = pd.read_csv(RESULTS_DIR / run / "scores.csv")
    s = s[~s.low_option_mass.astype(bool) & s.E.notna() & s.variant.isin(variants) & (s.repeat == 0)]
    return s.pivot_table(index=["model", "qid", "direction"], columns=["variant", "condition"], values="E")


def boot(x, n=5000):
    x = np.asarray(pd.Series(x).dropna())
    m = np.random.default_rng(0).choice(x, (n, len(x))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


e = load(RUN.name, ["P1", "PA", "PB", "PC"])
oo = load("20261115-ladder-confirm", ["P1", "P2"])
rows = []
for m in ["gpt-4.1-mini", "gpt-4.1"]:
    x = e.loc[m]
    d = x.index.get_level_values("direction")
    o = oo.loc[m]
    rows.append({"model": m, "variant": "P2 (option order, ladder-confirm)", "floor_vs_P1":
                 (o[("P2", "none")] - o[("P1", "none")]).abs().mean()})
    for v in ["P1", "PA", "PB", "PC"]:
        D = (x[(v, "democrat")] - x[(v, "republican")]) * d
        nz = D.dropna()[D.dropna().abs() > 1e-9]
        lo, hi = boot(D)
        rows.append({"model": m, "variant": v,
                     "floor_vs_P1": np.nan if v == "P1" else (x[(v, "none")] - x[("P1", "none")]).abs().mean(),
                     "mean_E_none": x[(v, "none")].mean(),
                     "mean_abs_logo_shift": pd.concat([(x[(v, c)] - x[(v, "none")]).abs() for c in
                                                       ["democrat", "republican"]]).mean(),
                     "party_D": D.mean(), "party_D_ci_lo": lo, "party_D_ci_hi": hi,
                     "party_expected_sign": f"{int((nz < 0).sum())}/{len(nz)}",
                     "party_wilcoxon_p": wilcoxon(nz, alternative="less").pvalue if len(nz) > 1 else np.nan})
t = pd.DataFrame(rows)
t.to_csv(RUN / "paraphrase.csv", index=False)
f = lambda v, s="+.2f": "–" if pd.isna(v) else format(v, s)  # noqa: E731
L = ["# Exp D: paraphrase noise floor (exploratory)", "",
     "Three approved rewordings of P1's first line (options and answer line identical): "
     "PA \"Here is a statement in an image. What do you think of it?\", PB \"Please give your personal opinion of the "
     "statement shown in the picture.\", PC \"To what extent do you agree with the statement displayed in the image?\". "
     "16 ladder statements, 1 repeat. Floor = mean |E_Px − E_P1| with no symbol. P2 row = option-order floor "
     "(P2 reverses the options; from results/20261115-ladder-confirm, repeat 0).", "",
     "| model | prompt | floor vs P1 (no symbol) | mean E, no symbol | mean abs logo shift | party D [95% CI] | "
     "expected sign | Wilcoxon p (1-sided) |", "|---|---|---|---|---|---|---|---|"]
for r in t.itertuples():
    L.append(f"| {r.model} | {r.variant} | {f(r.floor_vs_P1, '.2f')} | {f(r.mean_E_none, '.2f')} | "
             f"{f(r.mean_abs_logo_shift, '.2f')} | "
             + ("–" if pd.isna(r.party_D) else f"{r.party_D:+.2f} [{r.party_D_ci_lo:+.2f}, {r.party_D_ci_hi:+.2f}]")
             + f" | {r.party_expected_sign if isinstance(r.party_expected_sign, str) else '–'} | "
             f"{f(r.party_wilcoxon_p, '.3f')} |")
(RUN / "summary.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
