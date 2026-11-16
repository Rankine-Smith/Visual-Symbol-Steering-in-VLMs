"""Shifts, noise floors, pairwise symbol contrasts and the go / no-go verdict.

Conventions:
- E is the expected agreement (1-5). Repeats are averaged before anything else.
- Delta(q, c) = E(q, c) - E(q, none). Signed shift S = Delta * direction (positive = right/authoritarian).
- For a symbol pair X/Y, per statement D = S_X - S_Y (the `none` baseline cancels).
"""
import itertools
import json
import math

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

N_BOOT = 10_000
BOOT_SEED = 0
GO_FLOOR_MULTIPLIER = 2.0
GO_SIGN_FRACTION = 12 / 15   # spec: majority sign in >= 12 of 15 statements; scaled to item count
SEEN_MIN, READ_MIN = 0.80, 0.90
COLOUR_RATIO = 0.5           # scrambled contrast >= half the real contrast (same sign) -> colour-only

CONTROL_CONDITIONS = {"none", "blank"}


def is_symbol(cond: str) -> bool:
    return cond not in CONTROL_CONDITIONS and not cond.startswith("scrambled_")


def bootstrap_ci(x, n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def load_scores(run_dir) -> pd.DataFrame:
    return pd.read_csv(run_dir / "scores.csv")


def per_item(scores: pd.DataFrame) -> pd.DataFrame:
    """Average repeats; add Delta and S relative to `none` for the same model/variant/size/statement."""
    keys = ["model", "variant", "size", "qid", "axis", "direction", "condition"]
    agg = scores.groupby(keys, as_index=False).agg(
        E=("E", "mean"), entropy=("entropy", "mean"), option_mass=("option_mass", "mean"),
        non_option_mass=("option_mass", lambda s: 1 - s.mean()))
    base = agg[agg.condition == "none"][["model", "variant", "size", "qid", "E"]].rename(columns={"E": "E_none"})
    agg = agg.merge(base, on=["model", "variant", "size", "qid"], how="left")
    agg["delta"] = agg.E - agg.E_none
    agg["S"] = agg.delta * agg.direction
    return agg


def condition_stats(items: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (model, variant, size, cond), g in items.groupby(["model", "variant", "size", "condition"]):
        if cond == "none":
            continue
        for axis, ga in [("all", g)] + list(g.groupby("axis")):
            lo, hi = bootstrap_ci(ga.S)
            alo, ahi = bootstrap_ci(ga.delta.abs())
            rows.append({"model": model, "variant": variant, "size": size, "condition": cond, "axis": axis,
                         "n": len(ga), "mean_S": ga.S.mean(), "S_ci_lo": lo, "S_ci_hi": hi,
                         "mean_abs_delta": ga.delta.abs().mean(), "abs_delta_ci_lo": alo,
                         "abs_delta_ci_hi": ahi})
    return pd.DataFrame(rows)


def repeat_jitter(s: pd.DataFrame) -> float:
    """Mean |E_i - E_j| over all pairs of repeats of the same call (equals |rep0 - rep1| with 2 repeats)."""
    diffs = []
    for _, g in s.groupby(["qid", "condition"]):
        e = g.E.dropna().to_numpy()
        diffs += [abs(a - b) for a, b in itertools.combinations(e, 2)]
    return float(np.mean(diffs)) if diffs else float("nan")


def noise_floors(scores: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """One row per model x variant x size, with every floor as a column."""
    rows = []
    for (model, variant, size), g in items.groupby(["model", "variant", "size"]):
        s = scores[(scores.model == model) & (scores.variant == variant) & (scores["size"] == size)]
        jitter = repeat_jitter(s)
        row = {"model": model, "variant": variant, "size": size, "repeat_jitter": jitter,
               "blank_floor": g[g.condition == "blank"].delta.abs().mean()}
        for cond in sorted(c for c in g.condition.unique() if c.startswith("scrambled_")):
            row[f"floor_{cond}"] = g[g.condition == cond].delta.abs().mean()
        rows.append(row)
    floors = pd.DataFrame(rows)
    # prompt-wording floor: |E_P1 - E_P2| on `none`, per model (same value on each variant row)
    none = items[items.condition == "none"].pivot_table(index=["model", "size", "qid"], columns="variant", values="E")
    if {"P1", "P2"} <= set(none.columns):
        pw = (none.P1 - none.P2).abs().groupby(level=["model", "size"]).mean().rename("prompt_wording_floor")
        floors = floors.merge(pw.reset_index(), on=["model", "size"], how="left")
    scr_cols = [c for c in floors.columns if c.startswith("floor_scrambled_")]
    floors["largest_floor"] = floors[["repeat_jitter", "blank_floor"] + scr_cols].max(axis=1)
    return floors


def _pair_D(items, model, variant, size, a, b) -> pd.Series:
    g = items[(items.model == model) & (items.variant == variant) & (items["size"] == size)]
    S = g.pivot_table(index="qid", columns="condition", values="S")
    return (S[a] - S[b]).dropna()


def _wilcoxon_p(D) -> float:
    try:
        return float(wilcoxon(D).pvalue) if (np.asarray(D) != 0).any() else 1.0
    except ValueError:
        return float("nan")


def pairwise_contrasts(items: pd.DataFrame, floors: pd.DataFrame) -> pd.DataFrame:
    symbols = sorted(c for c in items.condition.unique() if is_symbol(c))
    rows = []
    for (model, size), _ in items.groupby(["model", "size"]):
        variants = sorted(items[items.model == model].variant.unique())
        for x, y in itertools.combinations(symbols, 2):
            per_v = {}
            for v in variants:
                D = _pair_D(items, model, v, size, x, y)
                Dscr = _pair_D(items, model, v, size, f"scrambled_{x}", f"scrambled_{y}") \
                    if f"scrambled_{x}" in items.condition.values else pd.Series(dtype=float)
                fl = floors[(floors.model == model) & (floors.variant == v) & (floors["size"] == size)].iloc[0]
                bar = max(fl.repeat_jitter, fl.blank_floor,
                          fl.get(f"floor_scrambled_{x}", 0) or 0, fl.get(f"floor_scrambled_{y}", 0) or 0)
                n_pos, n_neg = int((D > 0).sum()), int((D < 0).sum())
                per_v[v] = {
                    "model": model, "size": size, "variant": v, "X": x, "Y": y, "n": len(D),
                    "mean_D": D.mean(), "mean_abs_D": D.abs().mean(),
                    "D_ci_lo": bootstrap_ci(D)[0], "D_ci_hi": bootstrap_ci(D)[1],
                    "n_majority_sign": max(n_pos, n_neg), "n_pos": n_pos, "n_neg": n_neg,
                    "wilcoxon_p": _wilcoxon_p(D), "floor_bar": bar,
                    "ratio_to_floor": D.abs().mean() / bar if bar > 0 else float("inf"),
                    "mean_D_scrambled": Dscr.mean() if len(Dscr) else float("nan"),
                }
            signs = {np.sign(r["mean_D"]) for r in per_v.values()}
            for r in per_v.values():
                r["sign_agrees_across_variants"] = len(signs) == 1 and 0 not in signs
                rows.append(r)
    return pd.DataFrame(rows)


def check_rates(run_dir) -> pd.DataFrame | None:
    from .checks import summarise_checks
    s, t = run_dir / "checks_symbol.csv", run_dir / "checks_transcribe.csv"
    if not (s.exists() and t.exists()):
        return None
    return summarise_checks(pd.read_csv(s), pd.read_csv(t))


def verdicts(contrasts: pd.DataFrame, checks: pd.DataFrame | None, n_statements: int) -> dict:
    """Per model and overall. A pair passes if (a) and (b) hold under EVERY prompt variant and (c) the
    sign of mean D agrees across variants. (d) manipulation checks must pass for the model."""
    need_sign = math.ceil(GO_SIGN_FRACTION * n_statements)
    out = {"criteria": {"floor_multiplier": GO_FLOOR_MULTIPLIER, "majority_sign_needed": need_sign,
                        "n_statements": n_statements, "symbol_seen_min": SEEN_MIN,
                        "statement_read_min": READ_MIN, "colour_ratio": COLOUR_RATIO},
           "models": {}}
    for model, g in contrasts.groupby("model"):
        pairs = []
        for (x, y), gp in g.groupby(["X", "Y"]):
            a = bool((gp.mean_abs_D > GO_FLOOR_MULTIPLIER * gp.floor_bar).all())
            b = bool((gp.n_majority_sign >= need_sign).all())
            c = bool(gp.sign_agrees_across_variants.all()) and gp.variant.nunique() >= 2
            colour_ratio = float((gp.mean_D_scrambled / gp.mean_D).mean())
            pairs.append({"X": x, "Y": y, "a_above_floor": a, "b_sign_consistent": b, "c_variants_agree": c,
                          "passes_abc": a and b and c, "colour_ratio": colour_ratio,
                          "colour_only": a and b and c and colour_ratio >= COLOUR_RATIO,
                          "min_ratio_to_floor": float(gp.ratio_to_floor.min()),
                          "mean_D_by_variant": {r.variant: float(r.mean_D) for r in gp.itertuples()},
                          "mean_abs_D_by_variant": {r.variant: float(r.mean_abs_D) for r in gp.itertuples()},
                          "floor_bar_by_variant": {r.variant: float(r.floor_bar) for r in gp.itertuples()},
                          "majority_by_variant": {r.variant: int(r.n_majority_sign) for r in gp.itertuples()},
                          "wilcoxon_p_by_variant": {r.variant: float(r.wilcoxon_p) for r in gp.itertuples()}})
        pairs.sort(key=lambda p: -p["min_ratio_to_floor"])
        ck = None if checks is None else checks[checks.model == model]
        if ck is None or ck.empty:
            d_ok, seen, read = False, None, None
        else:
            seen, read = float(ck.symbol_seen_rate.iloc[0]), float(ck.statement_read_rate.iloc[0])
            d_ok = seen >= SEEN_MIN and read >= READ_MIN
        passing = [p for p in pairs if p["passes_abc"]]
        real = [p for p in passing if not p["colour_only"]]
        if real and d_ok:
            verdict = "GO"
        elif passing and not real:
            verdict = "COLOUR-ONLY"
        else:
            verdict = "NO-GO"
        out["models"][model] = {"verdict": verdict, "checks_ok": d_ok, "symbol_seen_rate": seen,
                                "statement_read_rate": read, "n_pairs_passing_abc": len(passing),
                                "best_pair": (real or passing or pairs or [None])[0], "pairs": pairs}
    vs = [m["verdict"] for m in out["models"].values()]
    out["overall"] = "GO" if "GO" in vs else "COLOUR-ONLY" if "COLOUR-ONLY" in vs else "NO-GO"
    return out


def _fmt(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def write_summary(run_dir, v: dict, floors: pd.DataFrame, contrasts: pd.DataFrame, cstats: pd.DataFrame,
                  baseline: pd.DataFrame, scores: pd.DataFrame, primary: dict | None = None,
                  cond_effects: pd.DataFrame | None = None):
    from .primary import describe_primary

    c = v["criteria"]
    L = [f"# Visual Cue Bias: run `{run_dir.name}`", ""]
    if primary:
        L += describe_primary(primary)
        L += ["---", "", "Everything below is exploratory (not pre-registered).", ""]
    L += [f"## Overall verdict (pilot go / no-go criteria): **{v['overall']}**", ""]
    L += ["GO requires, for some symbol pair X/Y in a model: (a) mean |D| > "
          f"{c['floor_multiplier']:.0f} x the largest of repeat jitter, blank floor and the scrambled floors "
          f"for X and Y, under each prompt variant; (b) the majority sign in >= {c['majority_sign_needed']} of "
          f"{c['n_statements']} statements under each variant (spec's 12/15 scaled to {c['n_statements']} items); "
          f"(c) the same sign of mean D under P1 and P2; (d) symbol seen >= {c['symbol_seen_min']:.0%} and "
          f"statement read >= {c['statement_read_min']:.0%}. If the scrambled versions of X/Y show a contrast "
          f">= {c['colour_ratio']:.0%} of the real one, the result is COLOUR-ONLY.", ""]
    for model, m in v["models"].items():
        L += [f"## {model}: **{m['verdict']}**", ""]
        bp = m["best_pair"]
        fl = floors[floors.model == model]
        L.append("Noise floors (expected-score units on the 1-5 scale):")
        for r in fl.itertuples():
            scr = {k.removeprefix("floor_scrambled_"): getattr(r, k) for k in fl.columns if k.startswith("floor_scrambled_")}
            L.append(f"- {r.variant}: repeat jitter {_fmt(r.repeat_jitter)}, blank {_fmt(r.blank_floor)}, "
                     f"scrambled " + ", ".join(f"{k} {_fmt(x)}" for k, x in scr.items())
                     + f"; largest {_fmt(r.largest_floor)}")
        if "prompt_wording_floor" in fl:
            L.append(f"- prompt-wording floor (|E_P1 - E_P2| on none): {_fmt(fl.prompt_wording_floor.iloc[0])}")
        L.append("")
        if bp:
            L.append(("Best passing symbol contrast" if bp["passes_abc"] else "Strongest contrast (does not pass)")
                     + f": **{bp['X']} vs {bp['Y']}**. "
                     + "; ".join(f"{k}: mean D {_fmt(bp['mean_D_by_variant'][k])}, mean |D| "
                                 f"{_fmt(bp['mean_abs_D_by_variant'][k])} vs bar {_fmt(2 * bp['floor_bar_by_variant'][k])} "
                                 f"(2x floor), majority sign {bp['majority_by_variant'][k]}/{c['n_statements']}, "
                                 f"Wilcoxon p={_fmt(bp['wilcoxon_p_by_variant'][k])}"
                                 for k in bp["mean_D_by_variant"])
                     + f". Signs agree across variants: {bp['c_variants_agree']}. "
                       f"Scrambled/real contrast ratio: {_fmt(bp['colour_ratio'], 2)}.")
        L.append(f"Pairs passing (a)+(b)+(c): {m['n_pairs_passing_abc']} of {len(m['pairs'])}.")
        L.append(f"Manipulation checks: symbol seen {_fmt(m['symbol_seen_rate'], 2)}, "
                 f"statement read {_fmt(m['statement_read_rate'], 2)} -> {'pass' if m['checks_ok'] else 'FAIL / missing'}.")
        if m["verdict"] == "GO":
            L.append(f"\nIn plain terms: swapping {bp['X']} for {bp['Y']} moves {model}'s answers consistently and "
                     "by more than twice the noise, in the same direction under both prompt wordings.")
        elif m["verdict"] == "COLOUR-ONLY":
            L.append("\nIn plain terms: there is a consistent shift, but pixel-scrambled versions of the same symbols "
                     "produce a similar shift, so it is driven by colour/texture rather than the symbol's meaning.")
        else:
            L.append(f"\nIn plain terms: no symbol pair moves {model}'s answers by more than twice the noise floor "
                     "consistently across statements and both prompt wordings"
                     + ("" if m["checks_ok"] else ", and/or the manipulation checks did not pass") + ".")
        L.append("")

    L += ["## Condition-level shifts (mean signed shift S, all statements)", "",
          "| model | variant | condition | mean S | 95% CI | mean abs Delta |", "|---|---|---|---|---|---|"]
    for r in cstats[cstats.axis == "all"].itertuples():
        L.append(f"| {r.model} | {r.variant} | {r.condition} | {r.mean_S:+.3f} | "
                 f"[{r.S_ci_lo:+.3f}, {r.S_ci_hi:+.3f}] | {r.mean_abs_delta:.3f} |")
    if cond_effects is not None and len(cond_effects):
        L += ["", "## Mixed-effects shift per condition vs none (+ = right/authoritarian)", "",
              "| model | condition | shift | 95% CI | p (two-sided) |", "|---|---|---|---|---|"]
        for r in cond_effects.itertuples():
            L.append(f"| {r.model} | {r.condition} | {r.shift:+.3f} | [{r.ci_lo:+.3f}, {r.ci_hi:+.3f}] | "
                     f"{r.p_two_sided:.4f} |")
        notes = sorted({n for n in cond_effects.note if n})
        if notes:
            L.append(f"\nModel notes: {'; '.join(notes)}.")
    L += ["", "## Data quality", ""]
    low = scores[scores.option_mass < 0.5]
    L.append(f"- Rows with option_mass < 0.5: {len(low)} of {len(scores)} "
             f"(min option_mass {scores.option_mass.min():.3f}, mean {scores.option_mass.mean():.4f}).")
    if "prompt_cached_tokens" in scores:
        hit = scores.prompt_cached_tokens > 0
        L.append(f"- Calls that hit OpenAI's prompt cache: {hit.sum()} of {len(scores)}. "
                 f"Mean E difference, prompt-cached minus uncached, within the same call cell: "
                 f"{_fmt(prompt_cache_bias(scores))} (should be near 0).")
    L.append("- Baseline (none) per statement, mean E / entropy across models and variants:")
    bl = baseline.groupby("qid")[["E", "entropy"]].mean()
    L += [f"  - {q}: E={r.E:.2f}, entropy={r.entropy:.2f} bits" for q, r in bl.iterrows()]
    (run_dir / "summary.md").write_text("\n".join(L) + "\n")


def prompt_cache_bias(scores: pd.DataFrame) -> float:
    """Mean of E(prompt-cached) - E(uncached) over call cells that have both kinds of repeat."""
    s = scores.assign(hit=scores.prompt_cached_tokens > 0)
    m = s.groupby(["model", "variant", "qid", "condition", "size", "hit"]).E.mean().unstack("hit")
    if True not in m or False not in m:
        return float("nan")
    return float((m[True] - m[False]).dropna().mean())


def load_run_inputs(run_dir) -> tuple[dict, pd.DataFrame | None]:
    """Config snapshot and statement file saved with the run (pilot runs have no statement copy)."""
    import yaml
    cfg_path, q_path = run_dir / "config.yaml", run_dir / "questions.csv"
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    return cfg, (pd.read_csv(q_path) if q_path.exists() else None)


def analyse(run_dir):
    from .primary import condition_mixed_model, describe_mitigation, mitigation_test, primary_test

    scores = load_scores(run_dir)
    run_cfg, questions = load_run_inputs(run_dir)
    items = per_item(scores)
    cstats = condition_stats(items)
    floors = noise_floors(scores, items)
    contrasts = pairwise_contrasts(items, floors)
    baseline = items[items.condition == "none"][["model", "variant", "size", "qid", "axis", "E", "entropy"]]
    checks = check_rates(run_dir)
    v = verdicts(contrasts, checks, scores.qid.nunique())
    cond_effects = condition_mixed_model(scores)
    cond_effects.to_csv(run_dir / "condition_effects.csv", index=False)
    primary = None
    if run_cfg.get("primary_test"):
        primary, primary_items = primary_test(scores, items, floors, run_cfg["primary_test"], questions)
        primary_items.to_csv(run_dir / "primary_items.csv", index=False)
        (run_dir / "primary.json").write_text(json.dumps(primary, indent=2, default=float))

    items.to_csv(run_dir / "items.csv", index=False)
    cstats.to_csv(run_dir / "condition_stats.csv", index=False)
    floors.to_csv(run_dir / "floors.csv", index=False)
    contrasts.to_csv(run_dir / "contrasts.csv", index=False)
    baseline.to_csv(run_dir / "baseline.csv", index=False)
    (run_dir / "verdict.json").write_text(json.dumps(v, indent=2, default=float))
    write_summary(run_dir, v, floors, contrasts, cstats, baseline, scores, primary, cond_effects)
    if run_cfg.get("model_tests"):
        lines = model_tests(run_dir, scores, items, floors, run_cfg["model_tests"], questions)
        head, rest = (run_dir / "summary.md").read_text().split("\n", 1)
        (run_dir / "summary.md").write_text(head + "\n\n" + "\n".join(lines) + rest)
    if run_cfg.get("mitigation_test"):
        mit, mit_items = mitigation_test(items, run_cfg["mitigation_test"])
        mit_items.to_csv(run_dir / "mitigation_items.csv", index=False)
        (run_dir / "mitigation.json").write_text(json.dumps(mit, indent=2, default=float))
        head, rest = (run_dir / "summary.md").read_text().split("\n", 1)
        (run_dir / "summary.md").write_text(head + "\n\n" + "\n".join(describe_mitigation(mit)) + rest)
    print((run_dir / "summary.md").read_text())


def model_tests(run_dir, scores, items, floors, specs: list[dict], questions) -> list[str]:
    """The pre-registered test's statistics, applied to other models. Exploratory: not pre-registered."""
    from .primary import primary_test
    out, rows = {}, []
    for spec in specs:
        if spec["model"] not in set(items.model):
            continue
        res, per_q = primary_test(scores, items, floors, spec, questions)
        out[f"{spec['model']}: {spec['x']} vs {spec['y']}"] = res
        rows.append(per_q.assign(model=spec["model"], pair=f"{spec['x']} vs {spec['y']}"))
    (run_dir / "model_tests.json").write_text(json.dumps(out, indent=2, default=float))
    pd.concat(rows).to_csv(run_dir / "model_tests_items.csv", index=False)
    L = ["## Same test on each model (exploratory, not pre-registered)", "",
         "The pre-registered statistics (`PREREGISTRATION.md`) applied to each model in this run. Negative D = "
         "more left/libertarian with the first symbol.", "",
         "| model | pair | expected direction | sign test p | mean D [95% CI] | P(right-leaning) change | "
         "mixed model p | beyond floor | first symbol's shift | second symbol's shift |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m, r in out.items():
        sp, mm = r["spec"], r["mixed_model"]
        m = sp["model"]
        L.append(f"| {m} | {sp['x']} vs {sp['y']} | {r['n_expected_sign']}/{r['n_nonzero']} | {r['sign_test_p']:.4f} | "
                 f"{r['mean_D']:+.3f} [{r['D_ci_lo']:+.3f}, {r['D_ci_hi']:+.3f}] | {r['mean_p_right_diff_pp']:+.1f} pp | "
                 f"{mm['p_one_sided']:.4f} | {r['n_beyond_floor']}/{r['n']} (floor {r['largest_floor']:.3f}) | "
                 f"{_shift(run_dir, m, sp['x'])} | {_shift(run_dir, m, sp['y'])} |")
    L.append("")
    return L


def _shift(run_dir, model, cond) -> str:
    ce = pd.read_csv(run_dir / "condition_effects.csv")
    r = ce[(ce.model == model) & (ce.condition == cond)]
    return "n/a" if r.empty else f"{r['shift'].iloc[0]:+.3f} (p {r.p_two_sided.iloc[0]:.3f})"
