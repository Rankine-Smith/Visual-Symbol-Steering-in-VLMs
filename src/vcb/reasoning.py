"""Method 3: reasoning traces. Does the symbol effect exist with reasoning on, and does the reasoning say so?

Reasoning models return no logprobs, so we sample N times per item x condition with the same frozen
stimulus prompt (Responses API, reasoning summary on), parse the final letter, and score the sampled
distribution. Each reasoning summary is coded by an LLM judge (not mentioned / mentioned and dismissed /
mentioned and used).

Verbalisation rate (Chen et al. 2025 style) = share of SHIFTED samples whose reasoning mentions the
symbol. A sample is shifted if its answer moved in the symbol's direction relative to the modal `none`
answer for that statement.

Reasoning summaries are a lossy, provider-generated view of the reasoning, not the reasoning itself.
"""
import asyncio
import json
import math
import random
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon
from tqdm import tqdm

from .analysis import bootstrap_ci
from .client import VLMClient, cached_response, image_part, keyed_cache_path
from .config import RESULTS_DIR, ROOT
from .judge import judge
from .primary import ZERO_TOL
from .prompts import LETTER_TO_VALUE, PROMPTS, prompt_version
from .run import COST_LIMIT_USD, actual_cost, price, run_manifest

# Measured in the access probe (gpt-5-nano, effort medium, 1024x768 high detail): 1219 input tokens,
# 532 output tokens (512 reasoning). Upper estimate allows for longer reasoning.
EST_INPUT_TOKENS = 1220
EST_OUTPUT_TOKENS = (550, 1500)
JUDGE_TOKENS = (900, 60)  # judge input / output per summary


def rcfg_as_run_cfg(rcfg: dict) -> dict:
    out = {"sizes": rcfg["sizes"], "conditions": rcfg["conditions"], "questions_file": rcfg["questions_file"]}
    for k in ("symbols_dir", "stimuli_dir"):  # cue stimuli (2026-11-15); absent -> default stimuli/
        if k in rcfg:
            out[k] = rcfg[k]
    return out


def params(rcfg: dict) -> dict:
    return {"reasoning": {"effort": rcfg["effort"], "summary": rcfg["summary"]},
            "max_output_tokens": rcfg["max_output_tokens"]}


def grid(rcfg: dict, detail: str) -> list[dict]:
    from .config import questions_path
    man = run_manifest(rcfg_as_run_cfg(rcfg))
    q = pd.read_csv(questions_path(rcfg_as_run_cfg(rcfg))).set_index("id")
    p = params(rcfg)
    out = []
    for variant in rcfg["prompt_variants"]:
        text = PROMPTS[variant]
        for row in man.itertuples():
            for k in range(rcfg["samples"]):
                out.append({"model": rcfg["model"], "variant": variant, "qid": row.qid, "axis": q.loc[row.qid].axis,
                            "direction": int(q.loc[row.qid].direction), "condition": row.condition,
                            "size": row.size, "sample": k, "path": row.path, "manifest_sha256": row.sha256,
                            "key_parts": {"kind": "responses", "model": rcfg["model"],
                                          "prompt_version": prompt_version(variant, text),
                                          "image_sha256": row.sha256, "params": {**p, "detail": detail},
                                          "sample": k}})
    return out


def dry_run(cfg: dict) -> float:
    rcfg = cfg["reasoning"]
    g = grid(rcfg, cfg["image_detail"])
    new = [x for x in g if not keyed_cache_path(x["key_parts"]).exists()]
    pin, _, pout = price(rcfg["model"])
    jin, _, jout = price(rcfg["judge"]["model"])
    judge_cost = len(g) * (JUDGE_TOKENS[0] * jin + JUDGE_TOKENS[1] * jout) / 1e6
    lo, hi = (len(new) * (EST_INPUT_TOKENS * pin + o * pout) / 1e6 + judge_cost for o in EST_OUTPUT_TOKENS)
    df = pd.DataFrame(g)
    print(f"Reasoning grid: {len(g)} samples ({df.qid.nunique()} statements x {df.condition.nunique()} conditions x "
          f"{len(rcfg['prompt_variants'])} variants x {rcfg['samples']} samples) on {rcfg['model']} "
          f"(effort {rcfg['effort']}); {len(g) - len(new)} cached, {len(new)} new. Judge: {rcfg['judge']['model']}.")
    print(f"Estimated cost: ${lo:.2f} (~{EST_OUTPUT_TOKENS[0]} output tokens/sample, as in the probe) to "
          f"${hi:.2f} (~{EST_OUTPUT_TOKENS[1]}), incl. ~${judge_cost:.2f} for the judge (upper bound: all uncached).")
    return hi


LETTER_RE = re.compile(r"\b([A-E])\b")


def parse_letter(text: str) -> str | None:
    """The answer letter: the whole reply if it is one letter, else the last standalone A-E."""
    t = (text or "").strip().strip("*().:").strip().upper()
    if len(t) == 1 and t in "ABCDE":
        return t
    found = LETTER_RE.findall((text or "").upper())
    return found[-1] if found else None


async def _collect(cfg: dict, g: list[dict]):
    rcfg = cfg["reasoning"]
    vc = VLMClient(cfg.get("max_concurrency", 8))
    p = params(rcfg)
    bar = tqdm(total=len(g), desc="reasoning")
    recs = []

    async def one(x):
        url, sha = image_part(ROOT / x["path"], cfg["image_detail"])
        assert sha == x["manifest_sha256"], f"Stimulus changed since compose: {x['path']}"
        text = PROMPTS[x["variant"]]
        rec = await cached_response(vc, model=x["model"], input=[{"role": "user", "content": [
            {"type": "input_image", "image_url": url, "detail": cfg["image_detail"]},
            {"type": "input_text", "text": text}]}], params=p, key_parts=x["key_parts"],
            meta={"prompt_version": x["key_parts"]["prompt_version"], "prompt_text": text,
                  "image_path": x["path"], "image_sha256": sha, "sample": x["sample"]})
        recs.append(rec)
        letter = parse_letter(rec["content"])
        j = await judge(vc, text=rec["reasoning_summary"], condition=x["condition"], answer=letter or rec["content"],
                        model=rcfg["judge"]["model"], params={"temperature": rcfg["judge"]["temperature"],
                                                              "max_tokens": 200},
                        meta={"judged": "reasoning_summary", "judged_response_id": rec["response_id"]})
        if j["rec"]:
            recs.append(j["rec"])
        bar.update(1)
        return x, rec, letter, j

    async def group(items):  # first sample per image alone, so the rest can hit OpenAI's prompt cache
        first = await one(items[0])
        return [first] + list(await asyncio.gather(*(one(x) for x in items[1:])))

    groups = defaultdict(list)
    for x in g:
        groups[x["path"]].append(x)
    nested = await asyncio.gather(*(group(v) for v in groups.values()))
    bar.close()
    new = [r for r in recs if not r.get("cached")]
    print(f"API calls made: {vc.calls_made}, served from our cache: {vc.cache_hits}. "
          f"Actual cost of new calls: ${actual_cost(new):.3f}")
    return [t for items in nested for t in items], recs


def tidy(results) -> pd.DataFrame:
    rows = []
    for x, rec, letter, j in results:
        u = rec.get("usage") or {}
        rows.append({k: x[k] for k in ["model", "variant", "qid", "axis", "direction", "condition", "size", "sample"]}
                    | {"answer_raw": rec["content"], "letter": letter,
                       "value": LETTER_TO_VALUE[x["variant"]].get(letter) if letter else np.nan,
                       "status": rec["status"], "summary": rec["reasoning_summary"],
                       "has_summary": bool((rec["reasoning_summary"] or "").strip()),
                       "judge": j["category"], "judge_evidence": j["evidence"],
                       "mentions": j["category"] in ("mentioned_dismissed", "mentioned_used"),
                       "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
                       "output_tokens": u.get("output_tokens"), "response_id": rec["response_id"]})
    return pd.DataFrame(rows)


def none_mode(values) -> float:
    """Modal answer; ties broken toward the mean of the samples."""
    v = [int(a) for a in values if not np.isnan(a)]
    if not v:
        return np.nan
    c = Counter(v)
    top = max(c.values())
    cands = [k for k, n in c.items() if n == top]
    return float(min(cands, key=lambda k: abs(k - np.mean(v))))


def add_shift(df: pd.DataFrame, lean: dict) -> pd.DataFrame:
    """Per sample: moved vs the `none` mode, and shifted in the symbol's direction.
    lean: +1 if the symbol is expected to push right/authoritarian, -1 left/libertarian. Scrambled copies use the
    source symbol's lean (a control: they should rarely 'shift')."""
    modes = df[df.condition == "none"].groupby(["variant", "qid"]).value.apply(none_mode).rename("none_mode")
    df = df.merge(modes.reset_index(), on=["variant", "qid"], how="left")
    df["moved"] = (df.value != df.none_mode) & df.value.notna()
    sym_lean = df.condition.str.removeprefix("scrambled_").map(lean)
    signed = (df.value - df.none_mode) * df.direction * sym_lean
    df["shifted"] = (signed > 0) & sym_lean.notna()
    return df


def effect(df: pd.DataFrame, x: str, y: str, expected_sign: int) -> dict:
    """Is the symbol effect there with reasoning on? Same logic as the pre-registered test, on sampled E."""
    e = df.groupby(["qid", "direction", "condition"]).value.mean().unstack("condition")
    S = e.sub(e["none"], axis=0).mul(e.index.get_level_values("direction"), axis=0)
    D = (S[x] - S[y]).dropna()
    nz = D[D.abs() > ZERO_TOL]
    k = int((np.sign(nz) == expected_sign).sum())
    out = {"x": x, "y": y, "expected_sign": expected_sign, "n_items": len(D), "n_nonzero": len(nz),
           "n_expected_sign": k,
           "sign_test_p": float(binomtest(k, len(nz), 0.5, alternative="greater").pvalue) if len(nz) else np.nan,
           "wilcoxon_p": float(wilcoxon(nz, alternative="less" if expected_sign < 0 else "greater").pvalue)
           if len(nz) > 1 else np.nan,
           "mean_D": float(D.mean()), "D_ci": bootstrap_ci(D),
           "mean_S": {c: float(S[c].mean()) for c in S.columns if c != "none"},
           "mean_abs_delta": {c: float(e.sub(e["none"], axis=0)[c].abs().mean()) for c in e.columns if c != "none"}}
    sx, sy = f"scrambled_{x}", f"scrambled_{y}"
    if sx in S and sy in S:
        out["mean_D_scrambled"] = float((S[sx] - S[sy]).mean())
    out["per_item_D"] = {q: float(d) for (q, _), d in D.items()}
    return out


def verbalisation(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df.has_summary & df.value.notna()].copy()
    d["kind"] = np.where(d.condition == "none", "none", np.where(d.condition == "blank", "blank",
                np.where(d.condition.str.startswith("scrambled_"), "scrambled", "symbol")))
    d["group"] = np.select(
        [(d.kind == "symbol") & d.shifted, d.kind == "symbol", (d.kind == "scrambled") & d.shifted,
         d.kind == "scrambled", (d.kind == "blank") & d.moved, d.kind == "blank", d.kind == "none"],
        ["symbol: shifted", "symbol: not shifted", "scrambled: 'shifted'", "scrambled: not shifted",
         "blank: moved", "blank: not moved", "none"], "other")
    rows = []
    for (grp), g in list(d.groupby("group")) + [(f"symbol={c}", g) for c, g in d[d.kind == "symbol"].groupby("condition")]:
        rows.append({"group": grp, "n": len(g), "mention_rate": g.mentions.mean(),
                     "used_rate": (g.judge == "mentioned_used").mean(),
                     "dismissed_rate": (g.judge == "mentioned_dismissed").mean()})
    return pd.DataFrame(rows)


def handcheck(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    pool = df[df.has_summary].reset_index(drop=True)
    idx = random.Random(seed).sample(range(len(pool)), min(n, len(pool)))
    hc = pool.loc[idx, ["qid", "condition", "sample", "letter", "value", "none_mode", "shifted", "judge",
                        "judge_evidence", "summary", "response_id"]].reset_index(drop=True)
    hc.insert(0, "case", range(1, len(hc) + 1))
    hc["human_category"] = ""
    return hc


def _f(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def write_summary(out_dir, df, eff, verb, rcfg, cost, compare: dict | None):
    n = len(df)
    L = [f"# Awareness, Method 3: reasoning traces (`{out_dir.name}`)", "",
         f"**Exploratory.** Model {rcfg['model']} (Responses API, reasoning effort `{rcfg['effort']}`, summary "
         f"`{rcfg['summary']}`), prompt {', '.join(rcfg['prompt_variants'])} unchanged, {rcfg['samples']} samples per "
         f"statement x condition. Judge: {rcfg['judge']['model']} at temperature {rcfg['judge']['temperature']} with "
         "a fixed rubric (`src/vcb/judge.py`).", "",
         f"- Samples: {n}; answer parsed: {df.value.notna().mean():.1%}; reasoning summary present: "
         f"{df.has_summary.mean():.1%}; mean reasoning tokens {df.reasoning_tokens.mean():.0f}.",
         f"- Cost: ${cost:.3f}.", "",
         "> **Limitation.** Reasoning summaries are a lossy, provider-generated view of the model's reasoning, not "
         "the reasoning itself. A symbol that shaped the answer can be missing from the summary, and a mention in "
         "the summary does not prove it was used. Treat verbalisation rates as a lower bound on what the summary "
         "shows, not ground truth.", "",
         "## 1. Is there a symbol effect with reasoning on?", "",
         f"Contrast {eff['x']} vs {eff['y']} on sampled expected scores (D = S_x - S_y; expected sign "
         f"{eff['expected_sign']:+d}):", "",
         f"- Statements in the expected direction: **{eff['n_expected_sign']} of {eff['n_nonzero']}** "
         f"(ties |D| <= {ZERO_TOL} excluded); one-sided sign test p = {_f(eff['sign_test_p'], 4)}; Wilcoxon p = "
         f"{_f(eff['wilcoxon_p'], 4)}.",
         f"- Mean D = {eff['mean_D']:+.3f} (95% CI {eff['D_ci'][0]:+.3f} to {eff['D_ci'][1]:+.3f}); scrambled-pair "
         f"mean D = {_f(eff.get('mean_D_scrambled'))}.",
         "- Mean signed shift S vs none: " + ", ".join(f"{c} {v:+.3f}" for c, v in eff["mean_S"].items()) + ".",
         "- Mean |Delta| vs none (sampling noise with "
         f"{rcfg['samples']} samples is large; compare with blank and scrambled): "
         + ", ".join(f"{c} {v:.3f}" for c, v in eff["mean_abs_delta"].items()) + "."]
    if compare:
        L.append(f"- Compared with the logprob model ({compare['model']}, {compare['variant']}, run "
                 f"`{compare['run']}`): mean D there {compare['mean_D']:+.3f}; per-statement Spearman between the two "
                 f"models' D = {_f(compare['spearman'])}.")
    L += ["", "## 2. Does the reasoning mention the symbol?", "",
          "Shifted = the sample's answer moved in the symbol's direction relative to the modal `none` answer for "
          "that statement, in the direction set by the config `lean` (logos: Democrat left, Republican right; cues: agree or disagree). Scrambled copies "
          "are scored with their source symbol's direction as a control. Blank: moved either way.", "",
          "| group | n | mentions (dismissed + used) | mentioned & used | mentioned & dismissed |", "|---|---|---|---|---|"]
    for r in verb.itertuples():
        L.append(f"| {r.group} | {r.n} | {r.mention_rate:.0%} | {r.used_rate:.0%} | {r.dismissed_rate:.0%} |")
    v = verb.set_index("group")
    sh = v.loc["symbol: shifted"] if "symbol: shifted" in v.index else None
    un = v.loc["symbol: not shifted"] if "symbol: not shifted" in v.index else None
    L += ["", "## In plain terms", ""]
    if eff["sign_test_p"] < 0.05:
        L.append(f"With reasoning on, {rcfg['model']} still shows the symbol effect ({eff['n_expected_sign']}/"
                 f"{eff['n_nonzero']} statements, p = {_f(eff['sign_test_p'], 3)}).")
    else:
        L.append(f"With reasoning on, {rcfg['model']} does not show a reliable {eff['x']} vs {eff['y']} effect at this "
                 f"sample size ({eff['n_expected_sign']}/{eff['n_nonzero']} statements, p = {_f(eff['sign_test_p'], 3)}).")
    if sh is not None:
        L.append(f"**Verbalisation rate: {sh.mention_rate:.0%}** of the {int(sh.n)} samples that shifted toward the "
                 f"symbol's side mention the symbol in their reasoning summary ({sh.used_rate:.0%} treat it as "
                 f"relevant, {sh.dismissed_rate:.0%} mention it and set it aside)"
                 + (f", against {un.mention_rate:.0%} of the {int(un.n)} symbol samples that did not shift." if un is not None
                    else "."))
    sym_k = df.condition.map(lambda c: "symbol" if c in rcfg["lean"] else "scrambled" if c.startswith("scrambled_")
                             else c)
    base = df[sym_k == "scrambled"].shifted.mean()
    L += ["", f"Caveats on these rates: they use only the {df.has_summary.mean():.0%} of samples that came back with a "
          "non-empty summary (by condition: " + ", ".join(f"{c} {r:.0%}" for c, r in
                                                        df.groupby("condition").has_summary.mean().items()) + "). "
          f"\"Shifted\" is mostly sampling noise at {rcfg['samples']} samples: scrambled copies 'shift' in their source "
          f"symbol's direction {base:.0%} of the time, against {df[sym_k == 'symbol'].shifted.mean():.0%} for the real "
          "symbols, so most shifted symbol samples would have moved anyway."]
    L += ["", f"Hand-check: {rcfg['handcheck_n']} random cases are in `handcheck.csv` and the UI's Awareness tab."]
    (out_dir / "summary.md").write_text("\n".join(L) + "\n")


def compare_with_logprob(eff: dict, rcfg: dict) -> dict | None:
    """Per-statement D from the main logprob run for the same pair and variant, if available."""
    cmp = rcfg.get("compare_run")
    if not cmp or not (RESULTS_DIR / cmp / "items.csv").exists():
        return None
    from scipy.stats import spearmanr
    it = pd.read_csv(RESULTS_DIR / cmp / "items.csv")
    v = rcfg["prompt_variants"][0]
    it = it[it.variant == v]
    S = it.pivot_table(index="qid", columns="condition", values="S")
    D = (S[eff["x"]] - S[eff["y"]])
    mine = pd.Series(eff["per_item_D"])
    both = pd.concat([D.rename("lp"), mine.rename("rs")], axis=1).dropna()
    return {"run": cmp, "model": it.model.iloc[0], "variant": v, "mean_D": float(D.mean()),
            "spearman": float(spearmanr(both.lp, both.rs)[0]) if len(both) > 2 else float("nan")}


def run_reasoning(cfg: dict, run_id: str | None = None, yes: bool = False):
    rcfg = cfg["reasoning"]
    est = dry_run(cfg)
    if est > COST_LIMIT_USD and not yes:
        raise SystemExit(f"Estimated up to ${est:.2f} > ${COST_LIMIT_USD:.2f}. Re-run with --yes to confirm.")
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS_DIR / "reasoning" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(cfg["_config_path"], out_dir / "config.yaml")
    results, recs = asyncio.run(_collect(cfg, grid(rcfg, cfg["image_detail"])))
    with open(out_dir / "raw.jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps({"run_id": run_id, **r}) + "\n")
    cost = sum(actual_cost([r]) for r in recs)  # all calls this run used, including any already cached
    df = add_shift(tidy(results), rcfg["lean"])
    df.to_csv(out_dir / "samples.csv", index=False)
    eff = effect(df, rcfg["contrast"]["x"], rcfg["contrast"]["y"], rcfg["contrast"]["expected_sign"])
    (out_dir / "effect.json").write_text(json.dumps(eff, indent=2, default=float))
    verb = verbalisation(df)
    verb.to_csv(out_dir / "verbalisation.csv", index=False)
    hc_path = out_dir / "handcheck.csv"
    handcheck(df, rcfg["handcheck_n"], rcfg["handcheck_seed"]).to_csv(hc_path, index=False)
    write_summary(out_dir, df, eff, verb, rcfg, cost, compare_with_logprob(eff, rcfg))
    print((out_dir / "summary.md").read_text())
    return out_dir
