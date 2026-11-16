"""Does the model know a corner symbol moved its answer? Cue symbols vs party logos (2026-11-15, exploratory).

Usage: python scripts/awareness_cues_analysis.py
Reads the Method 1 runs results/awareness/{20261114-180559 (logos, gpt-4.1-mini), 20261115-cues-41mini,
20261115-cues-luna, 20261115-mixed-41} and the Method 3 runs results/reasoning/20261115-cues-luna-{low,medium}
(reasoning-off comparison: results/20261115-explore-cues-luna, P4). Free: no API calls.
Writes results/awareness/20261115-cues-summary/{followup_by_condition,followup_shifted,reasoning_effect,
reasoning_by_condition,reasoning_dismissed_still_shifted}.csv and prints them.

Signed shift = movement in the direction the symbol pushes (positive = moved as the symbol suggests):
  cues   : agreement scale; thumbs_up / stars5 / approved / smile / most_agree / green push agreement (+1),
           their pairs push disagreement (-1). On the ideologically coded 11-item run, raw E (agreement) is used.
  logos  : ideology; Democrat -> left (-1), Republican -> right (+1) on the direction-coded scale.
"Clearly shifted" conversation = signed shift >= 0.5 points (on a 1-5 scale; >= 2x any repeat jitter we measured).
"Admits" = P(Yes) > 0.5 on the yes/no follow-up. "Says used" = open answer coded mentioned_used by the judge.
"""
import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402

LEAN = {"thumbs_up": 1, "thumbs_down": -1, "smile": 1, "frown": -1, "stars5": 1, "stars1": -1, "approved": 1,
        "rejected": -1, "most_agree": 1, "few_agree": -1, "green": 1, "red": -1, "democrat": -1, "republican": 1}
PAIRS = {"thumbs": ("thumbs_up", "thumbs_down"), "stars": ("stars5", "stars1"), "stamp": ("approved", "rejected")}
LOGOS = {"democrat", "republican"}
M1 = {"20261114-180559": "logos only (gpt-4.1-mini, 19 items)", "20261115-cues-41mini": "cues (gpt-4.1-mini, 19 items)",
      "20261115-cues-luna": "cues (gpt-6-luna, forced choice)", "20261115-mixed-41": "logos + cues (gpt-4.1, 11 items)"}
CLEAR = 0.5
OUT = RESULTS_DIR / "awareness" / "20261115-cues-summary"


def signed(df):
    lean = df.condition.map(LEAN)
    ideol = df.condition.isin(LOGOS)
    # logos: ideological direction; cues: raw agreement (direction is +1 on the agreement-coded files anyway)
    return np.where(ideol, df.delta * df.direction, df.delta) * lean


def followup():
    rows, shifted = [], []
    for run, label in M1.items():
        d = pd.read_csv(RESULTS_DIR / "awareness" / run / "items.csv")
        d = d.assign(run=label)
        d["signed"] = signed(d)
        d["admits"] = d.p_yes > 0.5
        d["says_used"] = d.open_judge == "mentioned_used"
        d["clear"] = d.signed >= CLEAR
        d["group"] = d.variant.map(lambda v: "ignore (P3)" if v == "P3" else "forced (P4/P5)" if v in ("P4", "P5")
                                   else "main (P1/P2)")
        for (m, g, c), x in d.groupby(["model", "group", "condition"]):
            rho = (spearmanr(x.p_yes, x.signed)[0] if c != "none" and x.p_yes.nunique() > 1 else np.nan)
            rows.append({"run": label, "model": m, "group": g, "condition": c, "n": len(x),
                         "mean_signed_shift": x.signed.mean(), "share_clearly_shifted": x.clear.mean(),
                         "mean_p_yes": x.p_yes.mean(), "admits_rate": x.admits.mean(),
                         "names_symbol_rate": x.open_mentions_symbol.mean(), "says_used_rate": x.says_used.mean(),
                         "dismissed_rate": (x.open_judge == "mentioned_dismissed").mean(),
                         "spearman_pyes_vs_shift": rho})
        sym = d[(d.condition != "none")].copy()
        sym["kind"] = np.where(sym.condition.isin(LOGOS), "logo", "cue")
        for (m, g, k), x in sym.groupby(["model", "group", "kind"]):
            cl = x[x.clear]
            shifted.append({"run": label, "model": m, "group": g, "kind": k, "n_conversations": len(x),
                            "n_clearly_shifted": len(cl),
                            "admits_when_shifted": cl.admits.mean() if len(cl) else np.nan,
                            "says_used_when_shifted": cl.says_used.mean() if len(cl) else np.nan,
                            "neither_admits_nor_says_used": (~cl.admits & ~cl.says_used).mean() if len(cl) else np.nan,
                            "admits_when_not_shifted": x[x.signed.abs() < 0.1].admits.mean(),
                            "n_not_shifted": int((x.signed.abs() < 0.1).sum())})
    return pd.DataFrame(rows), pd.DataFrame(shifted)


def reasoning():
    off = pd.read_csv(RESULTS_DIR / "20261115-explore-cues-luna" / "scores.csv")
    off = off[(off.variant == "P4") & ~off.low_option_mass.astype(bool) & off.E.notna()]
    e_off = off.groupby(["qid", "condition"]).E.mean().unstack()
    eff, byc, dis = [], [], []
    for effort in ("low", "medium"):
        p = RESULTS_DIR / "reasoning" / f"20261115-cues-luna-{effort}" / "samples.csv"
        if not p.exists():
            continue
        s = pd.read_csv(p)
        e_on = s.groupby(["qid", "condition"]).value.mean().unstack()
        for setting, e in (("reasoning off (logprob E)", e_off), (f"reasoning on, effort {effort} (8 samples)", e_on)):
            if setting.startswith("reasoning off") and effort == "medium":
                continue
            for pair, (pos, neg) in PAIRS.items():
                D = (e[neg] - e[pos]).dropna()
                nz = D[D.abs() > 0.01]
                eff.append({"setting": setting, "pair": pair, "n_items": len(D), "mean_D": D.mean(),
                            "expected_sign": f"{int((nz < 0).sum())}/{len(nz)}",
                            "wilcoxon_p": wilcoxon(nz, alternative="less").pvalue if len(nz) > 1 else np.nan,
                            "S_pos": (e[pos] - e["none"]).mean(), "S_neg": (e[neg] - e["none"]).mean()})
        none_mean = s[s.condition == "none"].groupby("qid").value.mean().rename("none_mean")
        s = s.merge(none_mean.reset_index(), on="qid")
        s["signed"] = (s.value - s.none_mean) * s.condition.map(LEAN)
        ok = s[s.has_summary & s.value.notna()]
        for c, x in ok.groupby("condition"):
            byc.append({"effort": effort, "condition": c, "n_with_summary": len(x),
                        "summary_rate": s[s.condition == c].has_summary.mean(),
                        "mention_rate": x.mentions.mean(), "used_rate": (x.judge == "mentioned_used").mean(),
                        "dismissed_rate": (x.judge == "mentioned_dismissed").mean(),
                        "mean_signed_shift_all": s[s.condition == c].signed.mean()})
        cues = ok[ok.condition != "none"]
        for cat, x in cues.groupby("judge"):
            dis.append({"effort": effort, "judge_category": cat, "n": len(x), "mean_signed_shift": x.signed.mean(),
                        "share_moved_toward_cue": (x.signed > 0).mean(), "share_moved_against": (x.signed < 0).mean()})
    return pd.DataFrame(eff), pd.DataFrame(byc), pd.DataFrame(dis)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 30)
    tabs = dict(zip(["followup_by_condition", "followup_shifted"], followup()))
    tabs.update(zip(["reasoning_effect", "reasoning_by_condition", "reasoning_dismissed_still_shifted"], reasoning()))
    for name, t in tabs.items():
        t.to_csv(OUT / f"{name}.csv", index=False)
        print(f"\n== {name}\n" + t.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
