"""Analyse the pre-assembled photo stimuli runs (2026-11-15, exploratory) and compare with the plain corner logos.

Usage: python scripts/preassembled_analysis.py
Reads results/20261115-explore-preassembled{,-grok}/scores.csv. Writes results/20261115-explore-preassembled/
comparison.csv and prints the tables.

Per model x prompt x statement: D = (E_democrat - E_republican) * direction (negative = more left with the
Democrat flag, the expected direction), with E averaged over repeats. No `none` image exists, so this
contrast is all we can measure. For the earlier corner-logo runs the same D is computed from their items.csv
(size 0.25, same statements, same prompts). Rows with low option mass (e.g. Grok refusals) are left out of E
and counted as refusals.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402

NEW = ["20261115-explore-preassembled", "20261115-explore-preassembled-grok"]
QIDS = ["q04", "q05"]
# earlier corner-logo runs with the same model and prompts
OLD = {
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
FORMAT = {"P1": "neutral", "P2": "neutral", "P4": "forced", "P5": "forced"}


def d_table(cells: pd.DataFrame) -> pd.DataFrame:
    """cells: model, variant, qid, direction, condition, E -> D per model x variant x qid."""
    w = cells.pivot_table(index=["model", "variant", "qid", "direction"], columns="condition", values="E").reset_index()
    w["D"] = (w["democrat"] - w["republican"]) * w["direction"]
    return w


def main():
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in NEW if (RESULTS_DIR / r / "scores.csv").exists()])
    s["refused"] = s.low_option_mass.astype(bool) | s.E.isna()
    ok = s[~s.refused]
    cells = ok.groupby(["model", "variant", "qid", "direction", "condition"]).agg(
        E=("E", "mean"), sd=("E", "std"), n=("E", "size"), p_neutral=("p3", "mean")).reset_index()
    new = d_table(cells)
    new["format"] = new.variant.map(FORMAT)

    # earlier corner-logo D, per model x variant x qid
    old_rows = []
    for (model, fmt), run in OLD.items():
        it = pd.read_csv(RESULTS_DIR / run / "items.csv")
        it = it[(it.model == model) & it.qid.isin(QIDS) & (it["size"] == 0.25)]
        if it.empty:
            continue
        old_rows.append(d_table(it[["model", "variant", "qid", "direction", "condition", "E"]])[
            ["model", "variant", "qid", "D"]].assign(old_run=run))
    old = pd.concat(old_rows).rename(columns={"D": "D_corner_logo"})
    comp = new.merge(old, on=["model", "variant", "qid"], how="left")
    comp = comp.rename(columns={"D": "D_photo_flag", "democrat": "E_dem", "republican": "E_rep"})

    # refusals and neutral share per model x format x condition
    s["format"] = s.variant.map(FORMAT)
    ref = s.groupby(["model", "format", "condition"]).refused.mean().unstack("condition")
    neu = cells.assign(format=cells.variant.map(FORMAT)).query("format == 'neutral'").groupby(
        ["model", "condition"]).p_neutral.mean().unstack("condition")
    jit = cells.groupby("model").sd.mean()

    out = RESULTS_DIR / NEW[0] / "comparison.csv"
    comp.to_csv(out, index=False)
    pd.set_option("display.width", 200)
    print(comp[["model", "variant", "qid", "E_dem", "E_rep", "D_photo_flag", "D_corner_logo"]].round(2).to_string(index=False))
    print("\nMean D per model x format (both statements, both wordings):")
    print(comp.groupby(["model", "format"])[["D_photo_flag", "D_corner_logo"]].mean().round(2).to_string())
    print("\nMean D per model x statement x format:")
    print(comp.groupby(["model", "qid", "format"])[["D_photo_flag", "D_corner_logo"]].mean().round(2).to_string())
    print("\nRefusal / unscored share:")
    print(ref.round(2).to_string())
    print("\nProbability on 'neither' (P1/P2):")
    print(neu.round(2).to_string())
    print("\nMean SD of E across repeats (repeat jitter):")
    print(jit.round(3).to_string())
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
