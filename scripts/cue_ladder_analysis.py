"""Cue ladder analysis (PRE-REGISTERED, PREREGISTRATION_cue_ladder.md, written 2026-11-15 before any call).

Usage: python scripts/cue_ladder_analysis.py
Reads results/20261115-cue-ladder-old and results/20261115-cue-ladder-new (scores.csv). Free: no API calls.
Writes results/20261115-cue-ladder-analysis/{cue_ladder.csv, split.csv, per_statement.csv, controls.csv, summary.md}.

Per model x prompt group (main = P1+P2, forced = P4+P5), per statement (negative = expected):
  D_party  = (E_dem - E_rep) * direction          (ideology-coded)
  D_thumbs = E_thumbs_down - E_thumbs_up;  D_stars = E_stars1 - E_stars5;  D_cue = mean of the two (agreement)
  D_colour = E_red - E_green;  D_scr = (E_scr_dem - E_scr_rep) * direction   (controls)
H1: D_cue < 0, one-sided Wilcoxon, Holm across models within group.
H2 (gpt-5.1 on): D_cue - D_party < 0, paired one-sided Wilcoxon, Holm across the 5 models within group.
"""
import sys

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, wilcoxon
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402

RUNS = ["20261115-cue-ladder-old", "20261115-cue-ladder-new"]
OUT = RESULTS_DIR / "20261115-cue-ladder-analysis"
GROUP = {"P1": "main", "P2": "main", "P4": "forced", "P5": "forced"}
ORDER = ["gpt-4.1-mini", "gpt-4.1", "gpt-5.1", "gpt-5.4-mini", "gpt-5.6-luna", "gpt-6-luna", "gpt-6.1-terra"]
NEWER = ORDER[2:]
ZERO_TOL = 1e-9
MIN_Q = 12
ALPHA = 0.05


def boot_ci(x, n=5000, seed=0):
    x = np.asarray(x.dropna())
    if len(x) == 0:
        return np.nan, np.nan
    m = np.random.default_rng(seed).choice(x, (n, len(x))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def wil(x, alternative):
    x = x.dropna()
    nz = x[x.abs() > ZERO_TOL]
    if len(nz) < 2:
        return np.nan
    return float(wilcoxon(nz, alternative=alternative).pvalue)


def load():
    s = pd.concat([pd.read_csv(RESULTS_DIR / r / "scores.csv") for r in RUNS if (RESULTS_DIR / r).exists()])
    s = s[~s.low_option_mass.astype(bool) & s.E.notna() & s.variant.isin(GROUP)]
    s["group"] = s.variant.map(GROUP)
    return s


def per_statement(s):
    # average over repeats, then over the two prompts of the group
    e = s.groupby(["model", "group", "variant", "qid", "axis", "direction", "condition"]).E.mean()
    e = e.groupby(["model", "group", "qid", "axis", "direction", "condition"]).mean().unstack("condition")
    w = e.reset_index()
    d = w.direction
    w["D_party"] = (w.democrat - w.republican) * d
    w["D_thumbs"] = w.thumbs_down - w.thumbs_up
    w["D_stars"] = w.stars1 - w.stars5
    w["D_cue"] = w[["D_thumbs", "D_stars"]].mean(axis=1, skipna=False)
    w["D_colour"] = w.red - w.green
    w["D_scr"] = (w.scrambled_democrat - w.scrambled_republican) * d
    w["A_party"] = w.democrat - w.republican  # raw agreement contrast, for the ideology-vs-agreement split
    w["diff_cue_minus_party"] = w.D_cue - w.D_party
    for c in ["democrat", "republican", "thumbs_up", "thumbs_down", "stars5", "stars1", "green", "red", "blank"]:
        w[f"dE_{c}"] = w[c] - w.none
    return w


def p_neither(s):
    p1 = s[s.variant == "P1"]
    return p1.groupby("model").p3.mean() if "p3" in p1 else pd.Series(dtype=float)


def jitter(s):
    r = s.pivot_table(index=["model", "variant", "qid", "condition"], columns="repeat", values="E")
    if r.shape[1] < 2:
        return pd.Series(dtype=float)
    return (r[0] - r[1]).abs().groupby("model").mean()


def main_table(w, s):
    rows = []
    neu, jit = p_neither(s), jitter(s)
    for (m, g), x in w.groupby(["model", "group"]):
        r = {"model": m, "group": g, "n_q_cue": int(x.D_cue.notna().sum())}
        for k in ["D_cue", "D_thumbs", "D_stars", "D_party", "D_colour", "D_scr", "diff_cue_minus_party"]:
            r[f"mean_{k}"] = x[k].mean()
            r[f"{k}_ci_lo"], r[f"{k}_ci_hi"] = boot_ci(x[k])
        nz = x.D_cue[x.D_cue.abs() > ZERO_TOL].dropna()
        r["cue_expected_sign"] = f"{int((nz < 0).sum())}/{len(nz)}"
        nzp = x.D_party[x.D_party.abs() > ZERO_TOL].dropna()
        r["party_expected_sign"] = f"{int((nzp < 0).sum())}/{len(nzp)}"
        r["H1_wilcoxon_p"] = wil(x.D_cue, "less")
        r["party_wilcoxon_p"] = wil(x.D_party, "less")
        r["H2_wilcoxon_p"] = wil(x.diff_cue_minus_party, "less") if m in NEWER else np.nan
        r["colour_wilcoxon_p_2sided"] = wil(x.D_colour, "two-sided")
        r["scr_wilcoxon_p_2sided"] = wil(x.D_scr, "two-sided")
        r["thumbs_wilcoxon_p"] = wil(x.D_thumbs, "less")
        r["stars_wilcoxon_p"] = wil(x.D_stars, "less")
        r["p_neither_P1"] = neu.get(m, np.nan) if g == "main" else np.nan
        r["repeat_jitter"] = jit.get(m, np.nan)
        r["excluded"] = r["n_q_cue"] < MIN_Q
        rows.append(r)
    t = pd.DataFrame(rows)
    t["H1_holm_p"] = np.nan
    t["H2_holm_p"] = np.nan
    for g, idx in t[~t.excluded].groupby("group").groups.items():
        t.loc[idx, "H1_holm_p"] = multipletests(t.loc[idx, "H1_wilcoxon_p"].fillna(1), method="holm")[1]
        nidx = [i for i in idx if t.loc[i, "model"] in NEWER]
        if nidx:
            t.loc[nidx, "H2_holm_p"] = multipletests(t.loc[nidx, "H2_wilcoxon_p"].fillna(1), method="holm")[1]
    t["H1_pass"] = (t.mean_D_cue < 0) & (t.H1_holm_p < ALPHA)
    t["H2_pass"] = np.where(t.model.isin(NEWER), (t.mean_diff_cue_minus_party < 0) & (t.H2_holm_p < ALPHA), np.nan)
    t["rank"] = t.model.map({m: i for i, m in enumerate(ORDER)})
    return t.sort_values(["group", "rank"]).drop(columns="rank")


def split_table(w):
    rows = []
    for (m, g), x in w.groupby(["model", "group"]):
        halves = {"right-coded (dir +1)": x[x.direction == 1], "left-coded (dir -1)": x[x.direction == -1]}
        for k, exp in [("A_party", {"right-coded (dir +1)": -1, "left-coded (dir -1)": 1}),
                       ("D_cue", {"right-coded (dir +1)": -1, "left-coded (dir -1)": -1})]:
            for h, y in halves.items():
                v = y[k].dropna()
                lo, hi = boot_ci(v)
                nz = v[v.abs() > ZERO_TOL]
                rows.append({"model": m, "group": g, "measure": k, "half": h, "n_q": len(v), "mean": v.mean(),
                             "ci_lo": lo, "ci_hi": hi, "expected_sign": exp[h],
                             "share_expected_sign": (np.sign(nz) == exp[h]).mean() if len(nz) else np.nan})
            a, b = halves["right-coded (dir +1)"][k].dropna(), halves["left-coded (dir -1)"][k].dropna()
            p = mannwhitneyu(a, b, alternative="two-sided").pvalue if len(a) and len(b) else np.nan
            rows.append({"model": m, "group": g, "measure": k, "half": "between halves (Mann-Whitney p, 2-sided)",
                         "mean": p})
    t = pd.DataFrame(rows)
    t["rank"] = t.model.map({m: i for i, m in enumerate(ORDER)})
    return t.sort_values(["group", "rank", "measure"]).drop(columns="rank")


def fmt_p(p):
    return "n/a" if pd.isna(p) else ("<0.001" if p < 0.001 else f"{p:.3f}")


def summary(t, sp):
    L = ["# Cue ladder: party logos vs approval cues on fresh balanced statements (PRE-REGISTERED)", "",
         "Pre-registration: `PREREGISTRATION_cue_ladder.md`. Runs: `results/20261115-cue-ladder-old` (gpt-4.1-mini, "
         "gpt-4.1; P1/P2; 1 repeat) and `results/20261115-cue-ladder-new` (gpt-5.1 on; P1/P2 and forced P4/P5; "
         "2 repeats). 16 statements. Negative D = moved the way the symbol suggests.", ""]
    for g in ["main", "forced"]:
        x = t[t.group == g]
        if x.empty:
            continue
        L += [f"## {g} prompts ({'P1/P2' if g == 'main' else 'P4/P5, no neutral option'})", "",
              "| model | cue D [95% CI] | H1 Holm p | pass | party D [95% CI] | party p (uncorr.) | cue − party, H2 Holm p "
              "| H2 pass | colour D (p 2-sided) | scrambled D (p) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in x.itertuples():
            h2 = "–" if pd.isna(r.H2_holm_p) else f"{r.mean_diff_cue_minus_party:+.2f}, {fmt_p(r.H2_holm_p)}"
            h2p = "–" if r.model not in NEWER else ("yes" if r.H2_pass else "no")
            L.append(f"| {r.model} | {r.mean_D_cue:+.2f} [{r.D_cue_ci_lo:+.2f}, {r.D_cue_ci_hi:+.2f}] "
                     f"({r.cue_expected_sign}) | {fmt_p(r.H1_holm_p)} | {'yes' if r.H1_pass else 'no'} | "
                     f"{r.mean_D_party:+.2f} [{r.D_party_ci_lo:+.2f}, {r.D_party_ci_hi:+.2f}] | "
                     f"{fmt_p(r.party_wilcoxon_p)} | {h2} | {h2p} | {r.mean_D_colour:+.2f} "
                     f"({fmt_p(r.colour_wilcoxon_p_2sided)}) | {r.mean_D_scr:+.2f} ({fmt_p(r.scr_wilcoxon_p_2sided)}) |")
        L.append("")
    m = t[t.group == "main"].set_index("model")
    f = t[t.group == "forced"].set_index("model")
    old_ok = all(m.loc[k, "H1_pass"] for k in ["gpt-4.1", "gpt-4.1-mini"] if k in m.index)
    n_new = int(f.loc[[k for k in NEWER if k in f.index], "H1_pass"].sum()) if len(f) else 0
    n_h2 = int(f.loc[[k for k in NEWER if k in f.index], "H2_pass"].astype(bool).sum()) if len(f) else 0
    L += ["## Pre-registered predictions", "",
          f"- H1, gpt-4.1 and gpt-4.1-mini pass (main group): **{'yes' if old_ok else 'no'}**.",
          f"- H1, at least 3 of 5 newer models pass (forced group): **{n_new} of {len(f)}** -> "
          f"**{'yes' if n_new >= 3 else 'no'}**.",
          f"- H1 prediction overall: **{'supported' if old_ok and n_new >= 3 else 'not supported'}**.",
          f"- H2, cue effect larger than party effect in at least 3 of 5 newer models (forced group): **{n_h2} of "
          f"{len(f)}** -> **{'supported' if n_h2 >= 3 else 'not supported'}**.", "",
          "## Ideology vs agreement split (secondary, descriptive)", "",
          "Raw agreement contrasts by statement half. A party effect that follows ideology flips sign between halves "
          "(Dem lowers agreement with right-coded statements, raises it with left-coded ones); a cue effect should be "
          "negative on both.", "",
          "| model | group | A_party right-coded | A_party left-coded | MW p | D_cue right-coded | D_cue left-coded | MW p |",
          "|---|---|---|---|---|---|---|---|"]
    for (mod, g), y in sp.groupby(["model", "group"], sort=False):
        def get(meas, half):
            v = y[(y.measure == meas) & (y.half == half)]["mean"]
            return v.iloc[0] if len(v) else np.nan
        R, Lh, B = "right-coded (dir +1)", "left-coded (dir -1)", "between halves (Mann-Whitney p, 2-sided)"
        L.append(f"| {mod} | {g} | {get('A_party', R):+.2f} | {get('A_party', Lh):+.2f} | {fmt_p(get('A_party', B))} | "
                 f"{get('D_cue', R):+.2f} | {get('D_cue', Lh):+.2f} | {fmt_p(get('D_cue', B))} |")
    L += ["", "Context columns (P(neither), repeat jitter, thumbs and stars separately, per-condition shifts) are in "
          "`cue_ladder.csv` and `per_statement.csv`."]
    return "\n".join(L) + "\n"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = load()
    w = per_statement(s)
    t = main_table(w, s)
    sp = split_table(w)
    w.to_csv(OUT / "per_statement.csv", index=False)
    t.to_csv(OUT / "cue_ladder.csv", index=False)
    sp.to_csv(OUT / "split.csv", index=False)
    (OUT / "summary.md").write_text(summary(t, sp))
    print((OUT / "summary.md").read_text())


if __name__ == "__main__":
    main()
