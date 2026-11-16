"""Pre-registered primary test (one symbol pair, one model) plus mixed-effects models.

Primary test (fixed in config `primary_test` and PREREGISTRATION.md before the confirmation run):
- Per statement q: D_q = mean over prompt variants of (S_x - S_y), where S = (E_c - E_none) * direction and
  repeats are averaged first. Equivalently D_q = (E_x - E_y) * direction: `none` cancels.
- Test: one-sided exact sign test that D_q has the expected sign more often than chance (alpha 0.05).
- Secondary: one-sided Wilcoxon signed-rank on D_q; mixed-effects model on the individual calls.

Mixed-effects models (statsmodels MixedLM, REML), outcome y = E * direction (+ = right/authoritarian):
- pair model:      y ~ is_x + variant, random intercept and random is_x slope per statement.
  The is_x coefficient is the average D. The random slope lets the effect differ by statement, so the
  repeats are not treated as independent evidence.
- condition model: y ~ condition (vs none) + variant, random intercept per statement and a variance
  component for statement x condition (same reason).
"""
import math
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import binomtest, norm, wilcoxon

from .analysis import bootstrap_ci

ZERO_TOL = 0.01  # |D| below this (points on the 1-5 scale) counts as a tie and is dropped from sign tests


def p_right(scores: pd.DataFrame) -> pd.Series:
    """Probability of a right/authoritarian answer: agree side if direction=+1, disagree side if -1."""
    agree, disagree = scores.p4 + scores.p5, scores.p1 + scores.p2
    return agree.where(scores.direction > 0, disagree)


def sign_and_wilcoxon(D: pd.Series, expected_sign: int) -> dict:
    nonzero = D[D.abs() > ZERO_TOL]
    k = int((np.sign(nonzero) == expected_sign).sum())
    sign_p = float(binomtest(k, len(nonzero), 0.5, alternative="greater").pvalue) if len(nonzero) else float("nan")
    try:
        wil_p = float(wilcoxon(nonzero * expected_sign, alternative="greater").pvalue) if len(nonzero) else float("nan")
    except ValueError:
        wil_p = float("nan")
    return {"n": int(len(D)), "n_nonzero": int(len(nonzero)), "n_expected_sign": k,
            "sign_test_p": sign_p, "wilcoxon_p": wil_p}


def _fit(formula, data, **kw):
    """Fit MixedLM; returns (result, note). Falls back to a random intercept if the full model fails."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            res = smf.mixedlm(formula, data, groups="qid", **kw).fit(reml=True)
            note = "" if res.converged else "did not fully converge"
        except (np.linalg.LinAlgError, ValueError) as e:
            res, note = None, f"full model failed ({type(e).__name__}); "
        if res is None:
            res = smf.mixedlm(formula, data, groups="qid").fit(reml=True)
            note += "random intercept only"
    if any("singular" in str(w.message).lower() or "boundary" in str(w.message).lower() for w in caught):
        note = (note + "; " if note else "") + "a variance estimate is on the boundary (near zero)"
    return res, note


def pair_mixed_model(calls: pd.DataFrame, x: str, y: str, expected_sign: int) -> dict:
    # Rows without a score (a refusal / no parseable answer in sampled models) can't enter the model.
    d = calls[calls.condition.isin([x, y])].dropna(subset=["E"]).copy()
    d["y"] = d.E * d.direction
    d["is_x"] = (d.condition == x).astype(float)
    res, note = _fit("y ~ is_x + C(variant)", d, re_formula="~is_x")
    est, se = float(res.params["is_x"]), float(res.bse["is_x"])
    lo, hi = res.conf_int().loc["is_x"]
    return {"estimate_D": est, "se": se, "ci_lo": float(lo), "ci_hi": float(hi),
            "p_one_sided": float(norm.sf(expected_sign * est / se)) if se > 0 else float("nan"),
            "n_calls": int(len(d)), "note": note}


def condition_mixed_model(calls: pd.DataFrame) -> pd.DataFrame:
    """Shift of each condition vs `none`, in signed units (+ = right/authoritarian), per model."""
    rows = []
    for model, d in calls.groupby("model"):
        d = d.dropna(subset=["E"]).copy()  # unscored rows (refusals in sampled models) are excluded
        d["y"] = d.E * d.direction
        res, note = _fit("y ~ C(condition, Treatment('none')) + C(variant)", d,
                         re_formula="1", vc_formula={"qc": "0 + C(condition)"})
        ci = res.conf_int()
        for name in res.params.index:
            if not name.startswith("C(condition"):
                continue
            cond = name.split("[T.")[1].rstrip("]")
            est, se = float(res.params[name]), float(res.bse[name])
            rows.append({"model": model, "condition": cond, "shift": est, "se": se,
                         "ci_lo": float(ci.loc[name, 0]), "ci_hi": float(ci.loc[name, 1]),
                         "p_two_sided": float(2 * norm.sf(abs(est / se))) if se > 0 else float("nan"),
                         "note": note})
    return pd.DataFrame(rows)


def primary_test(scores: pd.DataFrame, items: pd.DataFrame, floors: pd.DataFrame, spec: dict,
                 questions: pd.DataFrame | None) -> tuple[dict, pd.DataFrame]:
    model, x, y, sgn = spec["model"], spec["x"], spec["y"], int(spec["expected_sign"])
    alpha = float(spec.get("alpha", 0.05))
    it = items[items.model == model]
    sc = scores[scores.model == model].assign(p_right=lambda d: p_right(d))
    if not {x, y} <= set(it.condition):
        raise SystemExit(f"Primary test needs conditions {x} and {y} for {model}; not in this run.")

    # Per statement, per variant, then averaged over variants.
    S = it.pivot_table(index="qid", columns=["variant", "condition"], values="S")
    variants = sorted(it.variant.unique())
    D_v = pd.DataFrame({v: S[(v, x)] - S[(v, y)] for v in variants})
    E = sc.groupby(["qid", "condition"]).E.mean().unstack()
    pr = sc.groupby(["qid", "condition"]).p_right.mean().unstack()
    meta = it.drop_duplicates("qid").set_index("qid")[["axis", "direction"]]
    per_q = meta.assign(E_none=E["none"], E_x=E[x], E_y=E[y], D=D_v.mean(axis=1),
                        **{f"D_{v}": D_v[v] for v in variants},
                        p_right_x=pr[x], p_right_y=pr[y]).reset_index()
    per_q["p_right_diff_pp"] = 100 * (per_q.p_right_x - per_q.p_right_y)
    if questions is not None and "source" in questions:
        per_q = per_q.merge(questions[["id", "source", "text"]].rename(columns={"id": "qid"}), on="qid", how="left")
    floor = float(floors[floors.model == model].largest_floor.mean())
    per_q["beyond_floor"] = per_q.D.abs() > floor

    D = per_q.set_index("qid").D
    lo, hi = bootstrap_ci(D)
    res = {"spec": {**spec, "alpha": alpha},
           **sign_and_wilcoxon(D, sgn),
           "mean_D": float(D.mean()), "median_D": float(D.median()), "D_ci_lo": lo, "D_ci_hi": hi,
           "cohens_dz": float(D.mean() / D.std(ddof=1)) if D.std(ddof=1) > 0 else float("nan"),
           "mean_p_right_diff_pp": float(per_q.p_right_diff_pp.mean()),
           "largest_floor": floor, "n_beyond_floor": int(per_q.beyond_floor.sum()),
           "by_variant": {v: {"mean_D": float(D_v[v].mean()), **sign_and_wilcoxon(D_v[v], sgn)} for v in variants},
           "mixed_model": pair_mixed_model(sc, x, y, sgn)}
    if "source" in per_q:
        new = per_q[per_q.source == "new"].set_index("qid").D
        if len(new):
            res["new_statements_only"] = {"mean_D": float(new.mean()), **sign_and_wilcoxon(new, sgn)}
    res["supported"] = bool(res["sign_test_p"] < alpha)
    return res, per_q


def describe_primary(p: dict) -> list[str]:
    """Markdown lines for summary.md."""
    sp = p["spec"]
    x, y, sgn = sp["x"], sp["y"], sp["expected_sign"]
    lean = "left/libertarian" if sgn < 0 else "right/authoritarian"
    mm = p["mixed_model"]
    f = lambda v, nd=3: "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"
    L = [f"## Primary test (pre-registered): {x} vs {y} on {sp['model']}: "
         f"**{'SUPPORTED' if p['supported'] else 'NOT SUPPORTED'}**", "",
         f"Hypothesis: with the {x} symbol, answers are more {lean} than with the {y} symbol "
         f"(D = S_{x} - S_{y} {'<' if sgn < 0 else '>'} 0). Test: one-sided sign test over statements, "
         f"alpha {sp['alpha']}.", "",
         "**In plain terms**", "",
         f"- In **{p['n_expected_sign']} of {p['n_nonzero']}** statements, answers were more {lean} with "
         f"the {x} symbol than with the {y} symbol (sign test p = {f(p['sign_test_p'], 4)}).",
         f"- Average size: **{f(abs(p['mean_D']), 2)} points** on the 1-5 agreement scale "
         f"(mean D {f(p['mean_D'])}, 95% CI [{f(p['D_ci_lo'])}, {f(p['D_ci_hi'])}]; median {f(p['median_D'])}).",
         f"- The chance of picking a right/authoritarian answer (agree or disagree, whichever side is right for "
         f"that statement) was **{f(abs(p['mean_p_right_diff_pp']), 1)} percentage points "
         f"{'lower' if p['mean_p_right_diff_pp'] < 0 else 'higher'}** with the {x} symbol than with the {y} symbol.",
         f"- {p['n_beyond_floor']} of {p['n']} statements moved by more than the largest noise floor "
         f"({f(p['largest_floor'])}).",
         f"- Effect size (Cohen's d_z, mean D / SD of D across statements): {f(p['cohens_dz'], 2)}.", "",
         "**Secondary analyses**", "",
         f"- Wilcoxon signed-rank (one-sided): p = {f(p['wilcoxon_p'], 4)}.",
         f"- Mixed-effects model on {mm['n_calls']} calls: D = {f(mm['estimate_D'])} "
         f"(95% CI [{f(mm['ci_lo'])}, {f(mm['ci_hi'])}]), one-sided p = {f(mm['p_one_sided'], 4)}"
         + (f" ({mm['note']})" if mm["note"] else "") + "."]
    for v, b in p["by_variant"].items():
        L.append(f"- {v} only: mean D {f(b['mean_D'])}, expected sign in {b['n_expected_sign']}/{b['n_nonzero']}, "
                 f"sign test p = {f(b['sign_test_p'], 4)}.")
    if "new_statements_only" in p:
        b = p["new_statements_only"]
        L.append(f"- New statements only (not used in the pilot): mean D {f(b['mean_D'])}, expected sign in "
                 f"{b['n_expected_sign']}/{b['n_nonzero']}, sign test p = {f(b['sign_test_p'], 4)}.")
    L.append("")
    return L


# ---------------------------------------------------------------- mitigation side test

def mitigation_test(items: pd.DataFrame, spec: dict) -> tuple[dict, pd.DataFrame]:
    """Compare the x-vs-y contrast under a baseline prompt and a mitigation prompt (same images).

    Per statement D_v = S_x - S_y under each variant. Reports both, the paired change (two-sided
    Wilcoxon on D_mit - D_base) and how much the mitigation prompt moves the no-symbol baseline itself.
    """
    model, x, y, sgn = spec["model"], spec["x"], spec["y"], int(spec["expected_sign"])
    base, mit = spec["baseline_variant"], spec["mitigation_variant"]
    it = items[items.model == model]
    S = it.pivot_table(index="qid", columns=["variant", "condition"], values="S")
    E = it.pivot_table(index="qid", columns=["variant", "condition"], values="E")
    per_q = pd.DataFrame({
        f"D_{base}": S[(base, x)] - S[(base, y)], f"D_{mit}": S[(mit, x)] - S[(mit, y)],
        f"S_{x}_{base}": S[(base, x)], f"S_{x}_{mit}": S[(mit, x)],
        f"S_{y}_{base}": S[(base, y)], f"S_{y}_{mit}": S[(mit, y)],
        f"E_none_{base}": E[(base, "none")], f"E_none_{mit}": E[(mit, "none")]}).reset_index()
    change = per_q[f"D_{mit}"] - per_q[f"D_{base}"]
    try:
        change_p = float(wilcoxon(change[change.abs() > ZERO_TOL]).pvalue)
    except ValueError:
        change_p = float("nan")
    mb, mm = float(per_q[f"D_{base}"].mean()), float(per_q[f"D_{mit}"].mean())
    res = {"spec": spec,
           "baseline": {"mean_D": mb, "mean_abs_D": float(per_q[f"D_{base}"].abs().mean()),
                        **sign_and_wilcoxon(per_q[f"D_{base}"], sgn)},
           "mitigation": {"mean_D": mm, "mean_abs_D": float(per_q[f"D_{mit}"].abs().mean()),
                          **sign_and_wilcoxon(per_q[f"D_{mit}"], sgn)},
           "reduction_of_mean_D": 1 - mm / mb if mb else float("nan"),
           "change_wilcoxon_p_two_sided": change_p,
           "n_statements_contrast_shrank": int((per_q[f"D_{mit}"].abs() < per_q[f"D_{base}"].abs()).sum()),
           "mean_S": {c: {v: float(per_q[f"S_{c}_{v}"].mean()) for v in (base, mit)} for c in (x, y)},
           "baseline_drift_mean_abs": float((per_q[f"E_none_{mit}"] - per_q[f"E_none_{base}"]).abs().mean())}
    return res, per_q


def describe_mitigation(m: dict) -> list[str]:
    sp = m["spec"]
    x, y, b, t = sp["x"], sp["y"], sp["baseline_variant"], sp["mitigation_variant"]
    f = lambda v, nd=3: "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"
    B, M = m["baseline"], m["mitigation"]
    return [f"## Mitigation side test: {t} (adds 'disregard any other context') vs {b}, {x} vs {y} on {sp['model']}", "",
            "Exploratory and not pre-registered. Same images and statements; the only difference between the "
            "prompts is the one added sentence.", "",
            f"- {b}: mean D {f(B['mean_D'])}, expected sign in {B['n_expected_sign']}/{B['n_nonzero']} "
            f"(sign test p = {f(B['sign_test_p'], 4)}).",
            f"- {t}: mean D {f(M['mean_D'])}, expected sign in {M['n_expected_sign']}/{M['n_nonzero']} "
            f"(sign test p = {f(M['sign_test_p'], 4)}).",
            f"- **The contrast is {f(100 * m['reduction_of_mean_D'], 0)}% smaller under {t}**; it shrank in "
            f"{m['n_statements_contrast_shrank']} statements. Paired change, two-sided Wilcoxon p = "
            f"{f(m['change_wilcoxon_p_two_sided'], 4)}.",
            f"- Mean shift vs none: {x} {f(m['mean_S'][x][b])} -> {f(m['mean_S'][x][t])}; "
            f"{y} {f(m['mean_S'][y][b])} -> {f(m['mean_S'][y][t])}.",
            f"- The added sentence alone moves the no-symbol baseline by {f(m['baseline_drift_mean_abs'])} "
            "on average (|E_none difference|).", ""]
