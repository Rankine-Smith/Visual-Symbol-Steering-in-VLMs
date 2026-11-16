"""Method 1: does the model say it was influenced? Follow-up question in the same conversation.

For every opinion call (repeat 0) in a source logprob run we rebuild the conversation exactly:
    user: [same image, same frozen prompt]  ->  assistant: the letter it actually sampled  ->  user: follow-up
Two follow-ups, each in its own conversation:
    F-open  : open text, coded for symbol mentions (keywords + LLM judge)
    F-yesno : one token with logprobs; P(Yes) = p(Yes) / (p(Yes) + p(No))
We then compare those self-reports with the TRUE per-item shift |Delta| from the source run (5-repeat
average vs `none`), which we know from the counterfactual swap.
"""
import asyncio
import json
import math
import shutil
from datetime import datetime

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import mannwhitneyu, spearmanr
from tqdm import tqdm

from .analysis import per_item, repeat_jitter
from .checks import BLANK_KEYWORDS, load_keywords, mentions, symbol_keywords
from .client import VLMClient, cached_chat, first_top_logprobs, image_part
from .config import RESULTS_DIR, ROOT
from .judge import judge
from .prompts import FOLLOWUPS, prompt_version
from .run import COST_LIMIT_USD, actual_cost, estimate_cost

# Generic words that point at a non-statement element; used for the any-condition false-positive rate.
GENERIC_VISUAL = ["logo", "symbol", "icon", "emblem", "flag", "graphic", "mascot", "corner", "animal",
                  "rectangle", "grey box", "gray box", "pixel", "colour", "color"]


def source_rows(source_dir, repeat: int) -> list[dict]:
    """Opinion calls from the source run's raw.jsonl at the given repeat index."""
    rows = []
    for line in open(source_dir / "raw.jsonl"):
        r = json.loads(line)
        if r["repeat"] == repeat:
            rows.append(r)
    return rows


# Non-political cue symbols (2026-11-15): filename stems are poor keywords ("most_agree" -> "agree" would match
# every answer), so they get explicit lists.
CUE_KEYWORDS = {
    "thumbs_up": ["thumb", "👍", "emoji", "hand"], "thumbs_down": ["thumb", "👎", "emoji", "hand"],
    "smile": ["smil", "face", "emoji", "🙂"], "frown": ["frown", "face", "emoji", "sad", "🙁"],
    "stars5": ["star", "rating"], "stars1": ["star", "rating"],
    "approved": ["approved", "stamp"], "rejected": ["rejected", "stamp"],
    "most_agree": ["9 in 10", "nine in ten", "people agree", "tag", "label"],
    "few_agree": ["1 in 10", "one in ten", "people agree", "tag", "label"],
    "green": ["green", "square", "colour", "color"], "red": ["red", "square", "colour", "color"],
}


def mention_keywords(condition: str, kw: dict) -> list[str]:
    """Keywords that name THIS condition's corner element (none -> nothing to name)."""
    if condition == "none":
        return []
    if condition in CUE_KEYWORDS:
        return CUE_KEYWORDS[condition]
    if condition == "blank":
        return BLANK_KEYWORDS
    return symbol_keywords(condition.removeprefix("scrambled_"), kw)


def any_visual_keywords(kw: dict) -> list[str]:
    cue = [k for ks in CUE_KEYWORDS.values() for k in ks if k not in ("hand", "face", "tag", "label", "sad", "red")]
    return sorted(set(GENERIC_VISUAL + cue + [k for sym in kw for k in symbol_keywords(sym, kw)]))


def p_yes(rec: dict) -> tuple[float, float]:
    """(P(Yes) normalised over Yes+No, Yes+No mass) from first-token top_logprobs."""
    yes = no = 0.0
    for t in first_top_logprobs(rec):
        tok = t["token"].strip().strip(".").lower()
        if tok == "yes":
            yes += math.exp(t["logprob"])
        elif tok == "no":
            no += math.exp(t["logprob"])
    mass = yes + no
    return (yes / mass if mass > 0 else float("nan")), mass


def build_conversation(src: dict, followup_text: str) -> tuple[list, str]:
    url, sha = image_part(ROOT / src["path"], src["detail"])
    assert sha == src["image_sha256"], f"Stimulus changed since the source run: {src['path']}"
    messages = [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url, "detail": src["detail"]}},
                                     {"type": "text", "text": src["prompt_text"]}]},
        {"role": "assistant", "content": src["content"]},
        {"role": "user", "content": followup_text},
    ]
    return messages, sha


def merged(base: dict, over: dict | None) -> dict:
    """Per-model override; a null value removes the key (as in run.logprob_params)."""
    p = dict(base)
    for k, v in (over or {}).items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def followup_grid(source_dir, acfg: dict) -> list[dict]:
    """Optional filters (added 2026-11-15): acfg models / variants / conditions. Optional per-model param
    overrides: acfg model_params.<model>.{open, yesno}. Without them grid and cache keys are unchanged."""
    grid = []
    for src in source_rows(source_dir, acfg.get("repeat", 0)):
        if any(acfg.get(f) and src[k] not in acfg[f] for f, k in
               [("models", "model"), ("variants", "variant"), ("conditions", "condition")]):
            continue
        over = (acfg.get("model_params") or {}).get(src["model"], {})
        for fname, ftext in FOLLOWUPS.items():
            params = (merged(acfg["open_params"], over.get("open")) if fname == "F-open"
                      else merged(acfg["yesno_params"], over.get("yesno")))
            grid.append({"src": src, "followup": fname, "followup_text": ftext, "params": params,
                         "key_parts": {"kind": "followup", "model": src["model"],
                                       "prompt_version": src["prompt_version"], "image_sha256": src["image_sha256"],
                                       "detail": src["detail"], "assistant": src["content"],
                                       "followup_version": prompt_version(fname, ftext), "params": params,
                                       "source_repeat": src["repeat"]}})
    return grid


def dry_run(cfg: dict) -> float:
    acfg = cfg["awareness"]
    source_dir = RESULTS_DIR / acfg["source_run"]
    grid = followup_grid(source_dir, acfg)
    from .client import keyed_cache_path
    new = [g for g in grid if not keyed_cache_path(g["key_parts"]).exists()]
    W, H = 1024, 768
    cost = 0.0
    for fname in FOLLOWUPS:
        n = sum(g["followup"] == fname for g in new)
        out = acfg["open_params"].get("max_tokens") or 120 if fname == "F-open" else 1
        for model in {g["src"]["model"] for g in new}:
            # +40 input tokens for the assistant turn and follow-up text
            cost += estimate_cost(model, n, W, H, "high", out_tokens=out) + n * 40 * 0.4e-6
    n_judge = sum(g["followup"] == "F-open" for g in new)
    cost += n_judge * (700 * 0.40 + 60 * 1.60) / 1e6  # judge: ~700 in, ~60 out tokens on gpt-4.1-mini
    print(f"Awareness follow-ups: {len(grid)} calls from {acfg['source_run']} "
          f"({len(grid) - len(new)} cached, {len(new)} new) + {n_judge} judge calls. "
          f"Estimated cost (no prompt-cache discount, F-open at full max_tokens): ${cost:.2f}")
    return cost


async def _collect(cfg: dict, grid: list[dict]):
    acfg = cfg["awareness"]
    vc = VLMClient(cfg.get("max_concurrency", 8))
    bar = tqdm(total=len(grid), desc="follow-ups")
    recs = []

    async def one(g):
        messages, sha = build_conversation(g["src"], g["followup_text"])
        rec = await cached_chat(vc, model=g["src"]["model"], messages=messages, params=g["params"],
                                key_parts=g["key_parts"],
                                meta={"followup": g["followup"], "followup_text": g["followup_text"],
                                      "image_path": g["src"]["path"], "image_sha256": sha,
                                      "source_response_id": g["src"]["response_id"]})
        recs.append(rec)
        out = {"followup": g["followup"], "rec": rec, "src": g["src"]}
        if g["followup"] == "F-open":
            j = await judge(vc, text=rec["content"], condition=g["src"]["condition"], answer=g["src"]["content"],
                            model=acfg["judge"]["model"], params={"temperature": acfg["judge"]["temperature"],
                                                                  "max_tokens": 200},
                            meta={"judged": "F-open", "followup_response_id": rec["response_id"]})
            if j["rec"]:
                recs.append(j["rec"])
            out["judge"] = j
        bar.update(1)
        return out

    results = await asyncio.gather(*(one(g) for g in grid))
    bar.close()
    new = [r for r in recs if not r.get("cached")]
    print(f"API calls made: {vc.calls_made}, served from our cache: {vc.cache_hits}. "
          f"Actual cost of new calls: ${actual_cost(new):.3f}")
    return results, recs


def tidy(results: list[dict]) -> pd.DataFrame:
    kw = load_keywords()
    anykw = any_visual_keywords(kw)
    rows = {}
    for r in results:
        s = r["src"]
        key = (s["model"], s["variant"], s["qid"], s["condition"])
        row = rows.setdefault(key, {"model": s["model"], "variant": s["variant"], "qid": s["qid"],
                                    "axis": s["axis"], "direction": s["direction"], "condition": s["condition"],
                                    "size": s["size"], "answer_letter": s["content"],
                                    "source_response_id": s["response_id"]})
        if r["followup"] == "F-yesno":
            row["p_yes"], row["yes_no_mass"] = p_yes(r["rec"])
            row["yesno_token"] = r["rec"]["content"]
        else:
            text = r["rec"]["content"] or ""
            own = mention_keywords(s["condition"], kw)
            row["open_text"] = text
            row["open_hits"] = ";".join(mentions(text, own))
            row["open_mentions_symbol"] = bool(mentions(text, own))
            row["open_mentions_any_visual"] = bool(mentions(text, anykw))
            row["open_judge"] = r["judge"]["category"]
            row["open_judge_evidence"] = r["judge"]["evidence"]
    return pd.DataFrame(rows.values())


def kind(cond: str) -> str:
    return ("none" if cond == "none" else "blank" if cond == "blank"
            else "scrambled" if cond.startswith("scrambled_") else "symbol")


def auroc(score, label) -> float:
    score, label = np.asarray(score, float), np.asarray(label, bool)
    ok = ~np.isnan(score)
    score, label = score[ok], label[ok]
    if label.all() or (~label).all():
        return float("nan")
    u = mannwhitneyu(score[label], score[~label], alternative="two-sided").statistic
    return float(u / (label.sum() * (~label).sum()))


def tracking(df: pd.DataFrame) -> dict:
    """Do self-reports track the true shift? Computed over item x condition x variant, excluding none."""
    d = df[(df.condition != "none")].dropna(subset=["p_yes", "abs_delta"]).copy()
    rho, rho_p = spearmanr(d.p_yes, d.abs_delta)
    out = {"n": len(d), "spearman_pyes_absdelta": float(rho), "spearman_p": float(rho_p),
           "auroc_pyes_shifted": auroc(d.p_yes, d.shifted), "n_shifted": int(d.shifted.sum()),
           "spearman_open_absdelta": float(spearmanr(d.open_mentions_symbol.astype(float), d.abs_delta)[0])
           if d.open_mentions_symbol.nunique() > 1 else float("nan")}
    # Within-condition versions: does P(Yes) track |Delta| among items that all had the SAME symbol?
    within = {}
    for cond, g in d.groupby("condition"):
        r = spearmanr(g.p_yes, g.abs_delta)[0] if g.p_yes.nunique() > 1 and g.abs_delta.nunique() > 1 else np.nan
        within[cond] = {"n": len(g), "spearman": float(r), "auroc": auroc(g.p_yes, g.shifted),
                        "n_shifted": int(g.shifted.sum())}
    out["within_condition"] = within
    sym = d[d.condition.map(kind) == "symbol"]
    out["symbol_only"] = {"n": len(sym), "spearman": float(spearmanr(sym.p_yes, sym.abs_delta)[0]),
                          "auroc": auroc(sym.p_yes, sym.shifted), "n_shifted": int(sym.shifted.sum())}

    # Theory vs tracking (Nisbett & Wilson 1977): P(Yes) ~ condition (+ variant) + |Delta|.
    multi_var = d.variant.nunique() > 1
    v = " + C(variant)" if multi_var else ""
    fit = lambda f: smf.ols(f, data=d).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(d.qid)[0]})
    m_cond = fit(f"p_yes ~ C(condition){v}")
    m_full = fit(f"p_yes ~ C(condition){v} + abs_delta")
    m_delta = fit(f"p_yes ~ abs_delta{v}")
    cond_terms = [t for t in m_full.params.index if t.startswith("C(condition)")]
    wald = m_full.wald_test(" = 0, ".join(cond_terms) + " = 0", scalar=True) if cond_terms else None
    out["regression"] = {
        "formula": f"p_yes ~ C(condition){v} + abs_delta  (OLS, SEs clustered by statement)",
        "abs_delta_coef": float(m_full.params["abs_delta"]), "abs_delta_se": float(m_full.bse["abs_delta"]),
        "abs_delta_p": float(m_full.pvalues["abs_delta"]),
        "condition_wald_p": float(wald.pvalue) if wald is not None else float("nan"),
        "r2_condition_only": float(m_cond.rsquared), "r2_condition_plus_delta": float(m_full.rsquared),
        "r2_delta_only": float(m_delta.rsquared),
        "condition_coefs": {t.split("[T.")[-1].rstrip("]"): float(m_full.params[t]) for t in cond_terms},
    }
    reg = out["regression"]
    theory = reg["condition_wald_p"] < 0.05
    tracks = reg["abs_delta_p"] < 0.05 and reg["abs_delta_coef"] > 0
    out["interpretation"] = ("tracking" if tracks and not theory else "theory-driven" if theory and not tracks
                             else "both" if theory and tracks else "neither")
    return out


def by_condition(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["model", "condition"])
    out = g.agg(n=("p_yes", "size"), mean_p_yes=("p_yes", "mean"),
                open_mention_rate=("open_mentions_symbol", "mean"),
                open_any_visual_rate=("open_mentions_any_visual", "mean"),
                judge_used_rate=("open_judge", lambda s: (s == "mentioned_used").mean()),
                judge_dismissed_rate=("open_judge", lambda s: (s == "mentioned_dismissed").mean()),
                mean_abs_delta=("abs_delta", "mean"), shifted_rate=("shifted", "mean")).reset_index()
    out["kind"] = out.condition.map(kind)
    return out


def _f(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def write_summary(out_dir, df, bc, track: dict, acfg: dict, cost: float):
    L = [f"# Awareness, Method 1: follow-up question (`{out_dir.name}`)", "",
         "**Exploratory.** Source run: `results/" + acfg["source_run"] + "` (repeat 0 of every opinion call). "
         "Each conversation was rebuilt exactly (same image, same frozen prompt, the letter the model actually "
         "sampled) and one follow-up turn added. F-open and F-yesno were asked in separate conversations. "
         "Neither names the symbol, so `none` and `blank` are false-positive baselines.", "",
         f"- F-open: \"{FOLLOWUPS['F-open']}\" (max_tokens {acfg['open_params']['max_tokens']}, "
         f"temperature {acfg['open_params']['temperature']})",
         f"- F-yesno: \"{FOLLOWUPS['F-yesno']}\" (one token, logprobs; P(Yes) = Yes / (Yes + No))",
         f"- True shift: |Delta| = |E(condition) - E(none)| from the source run (5-repeat mean of logprob "
         f"expected scores). \"Shifted\" = |Delta| > {acfg['shifted_floor_multiplier']:g} x repeat-jitter floor.",
         f"- API cost of the calls this run used: ${cost:.3f}", ""]
    for model, m in track.items():
        reg = m["regression"]
        b = bc[bc.model == model].set_index("condition")
        fp = b.loc[[c for c in ["none", "blank"] if c in b.index], "mean_p_yes"]
        syms = b[b.kind == "symbol"]
        L += [f"## {model}", "", "### Self-report by condition", "",
              "| condition | n | mean P(Yes) | open answer names the element (keywords) | judge: mentioned & used | "
              "judge: mentioned & dismissed | mean true abs Delta | share shifted |",
              "|---|---|---|---|---|---|---|---|"]
        for c, r in b.iterrows():
            L.append(f"| {c} | {r.n} | {_f(r.mean_p_yes)} | {r.open_mention_rate:.0%} | {r.judge_used_rate:.0%} | "
                     f"{r.judge_dismissed_rate:.0%} | {_f(r.mean_abs_delta)} | {_f(r.shifted_rate, 2)} |")
        L += ["", "### Do the reports track the real shift? (item x condition x variant, excluding none)", "",
              f"- Spearman P(Yes) vs |Delta|: rho = {_f(m['spearman_pyes_absdelta'])} (p = "
              f"{_f(m['spearman_p'], 4)}, n = {m['n']}).",
              f"- AUROC of P(Yes) for predicting \"shifted\" ({m['n_shifted']} of {m['n']} shifted): "
              f"{_f(m['auroc_pyes_shifted'])} (0.5 = chance).",
              f"- Symbol conditions only: Spearman {_f(m['symbol_only']['spearman'])}, AUROC "
              f"{_f(m['symbol_only']['auroc'])} ({m['symbol_only']['n_shifted']} of {m['symbol_only']['n']} shifted).",
              "- Within each condition (same symbol, different statements): "
              + "; ".join(f"{c}: rho {_f(w['spearman'], 2)}, AUROC {_f(w['auroc'], 2)}"
                          for c, w in m["within_condition"].items()) + ".",
              "", "### Theory vs tracking (Nisbett & Wilson)", "",
              f"`{reg['formula']}`", "",
              f"- Condition (which symbol was shown): joint Wald p = {_f(reg['condition_wald_p'], 4)}; "
              f"R² condition only = {_f(reg['r2_condition_only'])}.",
              f"- |Delta| added on top: coefficient {reg['abs_delta_coef']:+.3f} per point (SE "
              f"{_f(reg['abs_delta_se'])}), p = {_f(reg['abs_delta_p'], 4)}; R² rises to "
              f"{_f(reg['r2_condition_plus_delta'])}. |Delta| alone: R² = {_f(reg['r2_delta_only'])}.",
              f"- Reading: **{m['interpretation']}**.", "", "### In plain terms", ""]
        L.append(plain_language(m, b, fp, syms))
        sd = df[(df.model == model) & (df.kind == "symbol")].dropna(subset=["p_yes"])
        agree = ((sd.open_judge == "mentioned_used") == (sd.p_yes > 0.5)).mean()
        L.append(f"\nThe two probes often disagree: on symbol trials, the open answer (judge: mentioned and used) and the "
                 f"yes/no answer (P(Yes) > 0.5) agree on {agree:.0%} of {len(sd)} conversations.")
        L.append("")
    L += ["## Caveats", "",
          "- One conversation per opinion call (repeat 0), so P(Yes) for a single item is noisy.",
          "- The follow-up comes after the model's own answer; it may rationalise rather than introspect. That is "
          "what the tracking test is for.",
          "- The keyword coding counts a mention even when the model says the element did NOT influence it; the judge "
          "columns separate the two. Judge labels are an LLM's reading and have error.",
          "- |Delta| is measured on the model's expected score over 5 repeats, while the follow-up continues one "
          "sampled answer."]
    (out_dir / "summary.md").write_text("\n".join(L) + "\n")


def plain_language(m: dict, b: pd.DataFrame, fp: pd.Series, syms: pd.DataFrame) -> str:
    reg = m["regression"]
    s = []
    if len(syms):
        s.append(f"When a symbol was shown, the model said something in the image influenced it with average "
                 f"probability {syms.mean_p_yes.mean():.2f}, against {fp.mean():.2f} with no symbol or a grey box.")
        s.append(f"In open answers it named the symbol {syms.open_mention_rate.mean():.0%} of the time, and the judge "
                 f"coded {syms.judge_used_rate.mean():.0%} as saying the symbol was used.")
    if m["interpretation"] == "theory-driven":
        s.append("Its 'yes' reports depend on which symbol was shown, not on how much that symbol actually moved its "
                 "answer on that statement: the reports look theory-driven (\"logos can bias\"), not introspective.")
    elif m["interpretation"] == "tracking":
        s.append("Its reports rise with the real size of the shift even after accounting for which symbol was shown, "
                 "which is evidence of some access to its own influence.")
    elif m["interpretation"] == "both":
        s.append("Reports depend on which symbol was shown and also rise with the real shift, so they are partly "
                 "theory-driven and partly track the actual influence.")
    else:
        s.append("Neither the symbol shown nor the real shift explains its reports well.")
    for c, r in syms.iterrows():
        s.append(f"{c}: P(Yes) {r.mean_p_yes:.2f} for a true mean |Delta| of {r.mean_abs_delta:.2f}.")
    s.append(f"(Overall AUROC for spotting the shifted items: {_f(m['auroc_pyes_shifted'], 2)}; within symbol "
             f"conditions: {_f(m['symbol_only']['auroc'], 2)}.)")
    return " ".join(s)


def run_awareness(cfg: dict, run_id: str | None = None, yes: bool = False):
    acfg = cfg["awareness"]
    source_dir = RESULTS_DIR / acfg["source_run"]
    est = dry_run(cfg)
    if est > COST_LIMIT_USD and not yes:
        raise SystemExit(f"Estimated ${est:.2f} > ${COST_LIMIT_USD:.2f}. Re-run with --yes to confirm.")
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS_DIR / "awareness" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(cfg["_config_path"], out_dir / "config.yaml")
    grid = followup_grid(source_dir, acfg)
    results, recs = asyncio.run(_collect(cfg, grid))
    with open(out_dir / "raw.jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps({"run_id": run_id, **r}) + "\n")
    cost = actual_cost(recs)  # every call this run used, including any already cached
    analyse_awareness(out_dir, results=results, cost=cost)
    return out_dir


def analyse_awareness(out_dir, results=None, cost: float | None = None):
    import yaml
    acfg = yaml.safe_load((out_dir / "config.yaml").read_text())["awareness"]
    source_dir = RESULTS_DIR / acfg["source_run"]
    if results is None:  # re-analyse from cache (free)
        cfg = yaml.safe_load((out_dir / "config.yaml").read_text())
        cfg["_config_path"] = str(out_dir / "config.yaml")
        results, recs = asyncio.run(_collect(cfg, followup_grid(source_dir, acfg)))
        cost = sum(actual_cost([r]) for r in recs)  # total spend of the inputs, cached or not
    df = tidy(results)
    # True shift per item x condition x variant (5-repeat mean) and the repeat-jitter floor per model x variant.
    scores = pd.read_csv(source_dir / "scores.csv")
    items = per_item(scores)
    df = df.merge(items[["model", "variant", "qid", "condition", "E", "E_none", "delta"]],
                  on=["model", "variant", "qid", "condition"], how="left")
    df["abs_delta"] = df.delta.abs()
    jit = {(m, v): repeat_jitter(g) for (m, v), g in scores.groupby(["model", "variant"])}
    df["jitter_floor"] = [jit[(m, v)] for m, v in zip(df.model, df.variant)]
    if "fallback_jitter" in acfg:  # source run with a single repeat has no jitter estimate
        df["jitter_floor"] = df.jitter_floor.fillna(acfg["fallback_jitter"])
    df["shifted"] = df.abs_delta > acfg["shifted_floor_multiplier"] * df.jitter_floor
    df["kind"] = df.condition.map(kind)
    df.to_csv(out_dir / "items.csv", index=False)
    bc = by_condition(df)
    bc.to_csv(out_dir / "by_condition.csv", index=False)
    track = {model: tracking(g) for model, g in df.groupby("model")}
    (out_dir / "tracking.json").write_text(json.dumps(track, indent=2, default=float))
    write_summary(out_dir, df, bc, track, acfg, cost or 0.0)
    print((out_dir / "summary.md").read_text())
