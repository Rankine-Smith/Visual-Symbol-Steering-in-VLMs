"""Analyse the logo-as-background runs (2026-11-15, exploratory) and compare with the plain corner logos.

Usage: python scripts/background_analysis.py
Reads results/20261115-explore-background{,-grok}/scores.csv. Writes results/20261115-explore-background/
per_statement.csv and tests.csv, and prints the tables.

Per model x prompt x statement, E is averaged over repeats (refusals / low option mass left out).
  D       = (E_democrat - E_republican) * direction   (negative = more left with the Democrat logo, expected)
  S_party = (E_party - E_none) * direction            (positive = more right/authoritarian than no logo)
D and S are then averaged over the two wordings of each format (neutral = P1/P2, forced = P4/P5), giving one
value per statement, and tested across the 6 statements (sign test + Wilcoxon, expected sign of D negative).
The corner-logo D for the same statements/prompts comes from the earlier runs' items.csv (size 0.25).
"""
import sys

import pandas as pd

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402
from vcb.primary import sign_and_wilcoxon  # noqa: E402

NEW = ["20261115-explore-background", "20261115-explore-background-grok"]
FORMAT = {"P1": "neutral", "P2": "neutral", "P4": "forced", "P5": "forced"}
OLD = {  # earlier corner-logo runs with the same model and prompts
    ("gpt-4.1-mini", "neutral"): "20261114-173050",
    ("gpt-6-luna", "neutral"): "20261114-newmodels",
    ("gpt-6.1-terra", "neutral"): "20261114-newmodels",
    ("gpt-6-sol", "neutral"): "20261114-newmodels",
    ("gpt-6-luna", "forced"): "20261114-noneutral-luna",
    ("gpt-6.1-terra", "forced"): "20261114-explore-nn_newmodels",
    ("gpt-6-sol", "forced"): "20261114-explore-nn_newmodels",
    ("grok-4.20-0309-non-reasoning", "neutral"): "20261114-grok",
    ("grok-4.7", "neutral"): "20261114-grok47",
    ("grok-4.7", "forced"): "20261114-explore-nn_grok47",
}


def contrasts(cells: pd.DataFrame) -> pd.DataFrame:
    w = cells.pivot_table(index=["model", "variant", "qid", "direction"], columns="condition", values="E").reset_index()
    w["D"] = (w["democrat"] - w["republican"]) * w["direction"]
    if "none" in w:
        w["S_dem"] = (w["democrat"] - w["none"]) * w["direction"]
        w["S_rep"] = (w["republican"] - w["none"]) * w["direction"]
    w["format"] = w.variant.map(FORMAT)
    return w


def main():
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in NEW])
    s["refused"] = s.low_option_mass.astype(bool) | s.E.isna()
    cells = s[~s.refused].groupby(["model", "variant", "qid", "direction", "condition"]).agg(
        E=("E", "mean"), n=("E", "size"), p_neutral=("p3", "mean")).reset_index()
    new = contrasts(cells)
    per_q = new.groupby(["model", "format", "qid"])[["D", "S_dem", "S_rep"]].mean().reset_index()

    old = []
    for (model, fmt), run in OLD.items():
        it = pd.read_csv(RESULTS_DIR / run / "items.csv")
        it = it[(it.model == model) & it.qid.isin(per_q.qid.unique()) & (it["size"] == 0.25)
                & it.variant.map(FORMAT).eq(fmt)]
        if not it.empty:
            old.append(contrasts(it).groupby(["model", "format", "qid"]).D.mean().rename("D_corner").reset_index())
    per_q = per_q.merge(pd.concat(old), on=["model", "format", "qid"], how="left")

    tests = []
    for (model, fmt), g in per_q.groupby(["model", "format"]):
        D = g.set_index("qid").D.dropna()
        st = sign_and_wilcoxon(D, -1)
        tests.append({"model": model, "format": fmt, "mean_D": D.mean(), "mean_D_corner": g.D_corner.mean(),
                      "mean_S_dem": g.S_dem.mean(), "mean_S_rep": g.S_rep.mean(),
                      "n_expected_sign": f"{st['n_expected_sign']}/{st['n_nonzero']}",
                      "sign_p": st["sign_test_p"], "wilcoxon_p": st["wilcoxon_p"]})
    tests = pd.DataFrame(tests)

    s["format"] = s.variant.map(FORMAT)
    ref = s.groupby(["model", "format", "condition"]).refused.mean().unstack("condition")
    neu = cells[cells.variant.map(FORMAT) == "neutral"].groupby(["model", "condition"]).p_neutral.mean().unstack()

    out = RESULTS_DIR / NEW[0]
    per_q.to_csv(out / "per_statement.csv", index=False)
    tests.to_csv(out / "tests.csv", index=False)
    pd.set_option("display.width", 220)
    print("Per model x format (6 statements):")
    print(tests.round(3).to_string(index=False))
    print("\nD per statement (background logo | corner logo):")
    print(per_q.pivot_table(index=["model", "format"], columns="qid", values=["D", "D_corner"]).round(2).to_string())
    print("\nRefusal / unscored share:")
    print(ref.round(2).to_string())
    print("\nProbability on 'neither' (P1/P2):")
    print(neu.round(2).to_string())
    print(f"\nwrote {out/'per_statement.csv'} and {out/'tests.csv'}")


if __name__ == "__main__":
    main()
