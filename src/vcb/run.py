"""Smoke test, statement screening, cost estimate, and the main logprob run."""
import asyncio
import json
import math
import re
import shutil
from collections import defaultdict
from datetime import datetime

import pandas as pd
from openai import AuthenticationError
from tqdm import tqdm

from .client import VLMClient, cache_path, cached_prompt_tokens, file_sha256, first_top_logprobs
from .config import CONFIG_PATH, DATA_DIR, RESULTS_DIR, manifest_path, ROOT, SMOKE_STATUS, load_config, questions_path
from .prompts import PROMPTS, prompt_version
from .scoring import score, token_to_letter

COST_LIMIT_USD = 3.0

# USD per 1M tokens (input, cached input, output), standard tier. Source: OpenAI pricing page as of 2026.
PRICES = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    # Reasoning models (Responses API). Source: developers.openai.com/api/docs/pricing, read 2026-11-14.
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-6-sol": (2.00, 0.20, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, 5.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    # Added 2026-11-15 for the model-ladder test. Same source, read 2026-11-15 (<272K context).
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5.1": (1.25, 0.125, 10.00),
    "gpt-5.2": (1.75, 0.175, 14.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.6-terra": (2.00, 0.20, 12.00),
    "gpt-5.6-sol": (4.00, 0.40, 20.00),
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6-astra": (10.00, 1.00, 50.00),
    # xAI. Source: docs.x.ai/docs/models, read 2026-11-14 (prompts < 200k tokens).
    "grok-4.20-0309-non-reasoning": (1.25, 0.20, 2.50),
    "grok-4.3": (1.25, 0.20, 2.50),
    "grok-4.5": (2.00, 0.30, 6.00),
    "grok-4.6": (2.00, 0.50, 6.00),
    "grok-4.7": (2.00, 0.50, 6.00),
}
# Newer models (gpt-5.x, gpt-6.x): image tokens measured in a probe on 2026-11-14
# (988 prompt tokens for a 1024x768 image + P1 = 908 image + 80 text).
MEASURED_IMAGE_TOKENS = 908
UNKNOWN_MODEL_PRICE = (2.50, 1.25, 10.00)  # assume gpt-4o pricing
TEXT_PROMPT_TOKENS = 80  # P1/P2 text + message overhead, rounded up
# Expected output tokens per opinion call for models that reason (reasoning tokens are billed as output).
# grok-4.7: 198 reasoning tokens at default effort in the 2026-11-14 probe; doubled for the upper estimate.
EST_OUTPUT_TOKENS = {"grok-4.7": 400}
# Share of input tokens OpenAI serves from its prompt cache when the same image is sent again
# (pilot: 1152 of 1312 tokens on gpt-4.1-mini). Used only for the optimistic estimate.
PROMPT_CACHE_SHARE = 0.85


def price(model: str) -> tuple[float, float, float]:
    return PRICES.get(model, UNKNOWN_MODEL_PRICE)


def image_tokens(model: str, W: int, H: int, detail: str = "high") -> int:
    """Estimate image input tokens using OpenAI's documented formulas.

    - Tile models (gpt-4o, gpt-4.1): fit in 2048x2048, scale shortest side to 768, count 512px tiles;
      tokens = 85 + 170 * tiles. gpt-4o-mini uses the same tiling but 2833 + 5667 * tiles.
    - Patch models (gpt-4.1-mini/nano): 32px patches (cap 1536), times 1.62 (mini) or 2.46 (nano).
    """
    if model.startswith("gpt-6") or model.startswith("gpt-5."):
        return MEASURED_IMAGE_TOKENS
    if model.startswith("grok-4.7"):
        return 2030  # measured 2026-11-14: 2109 prompt tokens for image + P1
    if model.startswith("grok"):
        return 970  # measured 2026-11-14: ~1045 prompt tokens for image + P1 on grok-4.20 / grok-4.3
    if model.startswith("gpt-4.1-mini") or model.startswith("gpt-4.1-nano"):
        patches = min(1536, math.ceil(W / 32) * math.ceil(H / 32))
        return math.ceil(patches * (1.62 if "mini" in model else 2.46))
    if detail == "low":
        tiles, base, per = 0, 85, 0
    else:
        s = min(1.0, 2048 / max(W, H))
        w, h = W * s, H * s
        s = min(1.0, 768 / min(w, h))
        w, h = w * s, h * s
        tiles = math.ceil(w / 512) * math.ceil(h / 512)
        base, per = 85, 170
    if model.startswith("gpt-4o-mini"):
        base, per = 2833, 5667
    return base + per * tiles


def estimate_cost(model: str, n_calls: int, W: int, H: int, detail: str, out_tokens: int = 1,
                  n_prompt_cached: int = 0) -> float:
    """List-price cost of n_calls; n_prompt_cached of them assumed to hit OpenAI's prompt cache."""
    pin, pcached, pout = price(model)
    tok_in = image_tokens(model, W, H, detail) + TEXT_PROMPT_TOKENS
    full = n_calls * (tok_in * pin + out_tokens * pout)
    saving = n_prompt_cached * tok_in * PROMPT_CACHE_SHARE * (pin - pcached)
    return (full - saving) / 1e6


def actual_cost(recs: list[dict]) -> float:
    """Billed cost of records, from the usage OpenAI returned (cached input at the cached rate)."""
    total = 0.0
    for r in recs:
        u = r.get("usage") or {}
        pin, pcached, pout = price(r["model_requested"])
        if "input_tokens" in u:  # Responses API usage (output includes reasoning tokens)
            tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
            cached = int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        else:
            tin, tout, cached = u.get("prompt_tokens", 0), u.get("completion_tokens", 0), cached_prompt_tokens(r)
            # xAI reports reasoning tokens outside completion_tokens but bills them as output.
            reasoning = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
            if u.get("total_tokens", 0) >= tin + tout + reasoning > tin + tout:
                tout += reasoning
        total += ((tin - cached) * pin + cached * pcached + tout * pout) / 1e6
    return total


def logprob_params(cfg: dict, model: str | None = None) -> dict:
    """API params for an opinion call. Config `model_params` can override per model (a null value removes the
    key). Newer models need e.g. reasoning_effort none, top_logprobs <= 5 and max_completion_tokens; we still
    read only the first output token's logprobs. Models without an override keep the original params (and
    therefore their cache keys)."""
    p = {"max_tokens": 1, "logprobs": True, "top_logprobs": 20, "temperature": cfg["temperature"]}
    for k, v in (cfg.get("model_params") or {}).get(model, {}).items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def active_models(cfg: dict) -> list[str]:
    """Config models, minus any the smoke test found unable to return logprobs with images."""
    models = list(cfg["models"])
    if SMOKE_STATUS.exists():
        status = json.loads(SMOKE_STATUS.read_text())
        dropped = [m for m in models if status.get(m, {}).get("ok") is False]
        if dropped:
            print(f"Dropping models that failed the smoke test: {dropped}")
        models = [m for m in models if m not in dropped]
    return models


def run_manifest(cfg: dict) -> pd.DataFrame:
    """Manifest rows for the configured statements, sizes and conditions."""
    manifest = pd.read_csv(manifest_path(cfg))
    questions = pd.read_csv(questions_path(cfg))
    missing = set(questions.id) - set(manifest.qid)
    if missing:
        raise SystemExit(f"Statements {sorted(missing)} have no stimuli. Run `python -m vcb compose` first.")
    manifest = manifest[manifest["size"].isin(cfg["sizes"]) & manifest.qid.isin(questions.id)]
    if cfg.get("conditions"):
        unknown = set(cfg["conditions"]) - set(manifest.condition)
        if unknown:
            raise SystemExit(f"Conditions {sorted(unknown)} not in the manifest. Re-run compose.")
        manifest = manifest[manifest.condition.isin(cfg["conditions"])]
    return manifest


def build_grid(cfg: dict) -> list[dict]:
    manifest = run_manifest(cfg)
    questions = pd.read_csv(questions_path(cfg)).set_index("id")
    grid = []
    for model in active_models(cfg):
        for variant in cfg["prompt_variants"]:
            for row in manifest.itertuples():
                q = questions.loc[row.qid]
                for rep in range(cfg["repeats"]):
                    grid.append({"model": model, "variant": variant, "qid": row.qid, "axis": q.axis,
                                 "direction": int(q.direction), "condition": row.condition,
                                 "size": row.size, "repeat": rep, "path": row.path,
                                 "manifest_sha256": row.sha256})
    return grid


def is_cached(g: dict, cfg: dict) -> bool:
    text = PROMPTS[g["variant"]]
    return cache_path(model=g["model"], prompt_version=prompt_version(g["variant"], text),
                      image_sha256=g["manifest_sha256"], params=logprob_params(cfg, g["model"]),
                      detail=cfg["image_detail"], repeat=g["repeat"]).exists()


def dry_run(cfg: dict) -> float:
    """Print call counts and cost. Returns the conservative (no prompt-cache discount) estimate."""
    grid = build_grid(cfg)
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    df = pd.DataFrame(grid)
    df["cached"] = [is_cached(g, cfg) for g in grid]
    print(f"Grid: {len(grid)} calls "
          f"({df.qid.nunique()} statements x {df.condition.nunique()} conditions x {len(cfg['sizes'])} sizes "
          f"x {len(cfg['prompt_variants'])} variants x {cfg['repeats']} repeats x {df.model.nunique()} models)")
    upper = lower = 0.0
    for model, g in df.groupby("model"):
        new = g[~g.cached]
        # Every new call except the first per image can hit OpenAI's prompt cache (image comes first).
        n_first = new.path.nunique()
        out = EST_OUTPUT_TOKENS.get(model, 1)
        hi = estimate_cost(model, len(new), W, H, cfg["image_detail"], out_tokens=out)
        lo = estimate_cost(model, len(new), W, H, cfg["image_detail"], out_tokens=out,
                           n_prompt_cached=len(new) - n_first)
        upper, lower = upper + hi, lower + lo
        print(f"  {model:14s} {len(g):5d} calls ({int(g.cached.sum())} already in our cache, {len(new)} new), "
              f"~{image_tokens(model, W, H, cfg['image_detail'])} image tokens/call -> ${lo:.2f} to ${hi:.2f}")
    print(f"Estimated cost of new calls: ${lower:.2f} (if OpenAI's prompt cache hits) to ${upper:.2f} (if it never does)")
    print("Estimate method: OpenAI's documented image-token formulas for a "
          f"{W}x{H} image at detail={cfg['image_detail']} (see run.image_tokens) x list prices; "
          "verified against usage.prompt_tokens in the smoke test.")
    return upper


async def _smoke(cfg: dict):
    manifest = pd.read_csv(manifest_path(cfg))
    row = manifest[(manifest.qid == "q01") & (manifest.condition == "none")].iloc[0]
    client = VLMClient(cfg["max_concurrency"])
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    status = {}
    for model in cfg["models"]:
        print(f"\n=== {model} on {row.path} (P1) ===")
        try:
            rec = await client.complete(model=model, prompt_text=PROMPTS["P1"],
                                        prompt_version=prompt_version("P1", PROMPTS["P1"]),
                                        image_path=ROOT / row.path, detail=cfg["image_detail"],
                                        params=logprob_params(cfg, model), repeat=0)
        except AuthenticationError as e:
            # A bad key says nothing about model support: stop without recording any model as dropped.
            raise SystemExit(f"OpenAI rejected the API key (401). Fix OPENAI_API_KEY in .env. ({e.message[:60]}...)")
        except Exception as e:  # noqa: BLE001 - report any API failure and drop the model
            print(f"  FAILED: {type(e).__name__}: {e}")
            status[model] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            continue
        tops, scored_from = tops_or_sample(rec)
        print(f"  scored from: {scored_from}")
        print(f"  sampled token: {rec['content']!r}  (returned model {rec['model_returned']})")
        if rec.get("usage"):
            est = image_tokens(model, W, H, cfg["image_detail"]) + TEXT_PROMPT_TOKENS
            print(f"  prompt_tokens: {rec['usage']['prompt_tokens']} (our estimate {est})")
        for t in tops:
            print(f"    {t['token']!r:10s} p={math.exp(t['logprob']):.4f}")
        s = score(tops, "P1")
        print(f"  option_mass={s['option_mass']:.4f}  E={s['E']:.3f}")
        ok = len(tops) > 0
        status[model] = {"ok": ok, "n_top_logprobs": len(tops), "option_mass": s["option_mass"],
                         "prompt_tokens": (rec.get("usage") or {}).get("prompt_tokens")}
        if not ok:
            print("  No logprobs returned -> model will be dropped.")
    SMOKE_STATUS.parent.mkdir(exist_ok=True)
    prev = json.loads(SMOKE_STATUS.read_text()) if SMOKE_STATUS.exists() else {}
    SMOKE_STATUS.write_text(json.dumps({**prev, **status}, indent=2))
    working = [m for m, s in status.items() if s["ok"]]
    print(f"\nWorking models: {working}")
    if not working:
        raise SystemExit("No model returned logprobs with image input.")


def smoke(cfg: dict):
    asyncio.run(_smoke(cfg))


async def call_grouped_by_image(client: VLMClient, grid: list[dict], cfg: dict, desc: str):
    """Make every call in `grid`, sending the first call for each image on its own and the rest after it.

    The image is the first part of the message, so once one call for an image has finished, the others
    (other prompt variant, other repeats) share a long identical prefix and OpenAI bills most of their
    input at the cached rate. The pilot showed no systematic difference in E between prompt-cached and
    uncached calls (mean signed difference 0.001 +/- 0.025). Returns [(grid_item, record), ...].
    """
    bar = tqdm(total=len(grid), desc=desc)

    async def one(g):
        text = PROMPTS[g["variant"]]
        rec = await client.complete(model=g["model"], prompt_text=text,
                                    prompt_version=prompt_version(g["variant"], text),
                                    image_path=ROOT / g["path"], detail=cfg["image_detail"],
                                    params=logprob_params(cfg, g["model"]), repeat=g["repeat"])
        assert rec["image_sha256"] == g["manifest_sha256"], f"Stimulus changed since compose: {g['path']}"
        bar.update(1)
        return g, rec

    async def group(items):
        first = await one(items[0])
        return [first] + list(await asyncio.gather(*(one(g) for g in items[1:])))

    groups = defaultdict(list)
    for g in grid:
        groups[(g["model"], g["path"])].append(g)
    nested = await asyncio.gather(*(group(items) for items in groups.values()))
    bar.close()
    return [pair for items in nested for pair in items]


LEADING_LETTER = re.compile(r"^[\s*_(\[]*([A-E])(?![A-Za-z])")


def tops_or_sample(rec: dict) -> tuple[list[dict], str]:
    """First-token top_logprobs if the model returned them; otherwise (models without logprobs, e.g. Grok) the
    sampled answer letter as a one-point distribution. Averaging repeats then gives the sampled mean E."""
    tops = first_top_logprobs(rec)
    if tops:
        return tops, "logprobs"
    # The answer is the leading letter, allowing markdown bold and a trailing explanation ("**B**", "D\n\nThe ...").
    m = LEADING_LETTER.match(rec.get("content") or "")
    return ([{"token": m.group(1), "logprob": 0.0}] if m else []), "sample"


def score_row(g: dict, rec: dict, **extra) -> dict:
    tops, scored_from = tops_or_sample(rec)
    s = score(tops, g["variant"])
    return {**extra, "model": g["model"], "variant": g["variant"], "qid": g["qid"], "axis": g["axis"],
            "direction": g["direction"], "condition": g["condition"], "size": g["size"], "repeat": g["repeat"],
            **{f"p{v}": s[f"p{v}"] for v in range(1, 6)},
            "E": s["E"], "entropy": s["entropy"], "option_mass": s["option_mass"],
            "low_option_mass": s["low_option_mass"], "sampled_token": rec["content"],
            "image_sha256": rec["image_sha256"], "prompt_cached_tokens": cached_prompt_tokens(rec),
            "scored_from": scored_from}


def print_spend(client: VLMClient, results: list):
    new = [rec for _, rec in results if not rec.get("cached")]
    print(f"API calls made: {client.calls_made}, served from our cache: {client.cache_hits}")
    if new:
        hit = sum(cached_prompt_tokens(r) > 0 for r in new)
        print(f"Actual cost of new calls: ${actual_cost(new):.3f} "
              f"({hit} of {len(new)} hit OpenAI's prompt cache)")


async def _run(cfg: dict, run_id: str):
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(cfg.get("_config_path", CONFIG_PATH), run_dir / "config.yaml")
    shutil.copy(questions_path(cfg), run_dir / "questions.csv")
    grid = build_grid(cfg)
    client = VLMClient(cfg["max_concurrency"])
    results = await call_grouped_by_image(client, grid, cfg, desc="calls")
    rows = []
    with open(run_dir / "raw.jsonl", "w") as f:
        for g, rec in results:
            f.write(json.dumps({"run_id": run_id, **g, **rec}) + "\n")
            rows.append(score_row(g, rec, run_id=run_id))
    scores = pd.DataFrame(rows)
    scores.to_csv(run_dir / "scores.csv", index=False)
    print(f"\nRun {run_id}: {len(scores)} rows -> {run_dir / 'scores.csv'}")
    print_spend(client, results)
    low = scores[scores.low_option_mass]
    if len(low):
        print(f"WARNING: {len(low)} rows with option_mass < 0.5")
    return run_dir


def run(cfg: dict, run_id: str | None = None, yes: bool = False):
    est = dry_run(cfg)
    if est > COST_LIMIT_USD and not yes:
        raise SystemExit(f"Estimated cost up to ${est:.2f} > ${COST_LIMIT_USD:.2f}. Re-run with --yes to confirm.")
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    return asyncio.run(_run(cfg, run_id))


# ---------------------------------------------------------------- statement screening

SCREEN_DIR = DATA_DIR / "screen"


def screen_grid(cfg: dict) -> tuple[list[dict], pd.DataFrame]:
    """Render the `none` image for every candidate statement; one call per variant x screen repeat."""
    from .compose import render_statement_layer

    sc = cfg["screen"]
    cands = pd.read_csv(ROOT / sc["candidates_file"])
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    size = cfg["sizes"][0]
    grid = []
    for q in cands.itertuples():
        # Same renderer and filename as `compose`, so the image (and therefore our cache key) is identical.
        path = ROOT / "stimuli" / f"{q.id}__none__s{size}.png"
        path.parent.mkdir(exist_ok=True)
        render_statement_layer(q.text, W, H)[0].save(path, format="PNG", optimize=False)
        for variant in cfg["prompt_variants"]:
            for rep in range(sc.get("repeats", 1)):
                grid.append({"model": sc["model"], "variant": variant, "qid": q.id, "axis": q.axis,
                             "direction": int(q.direction), "condition": "none", "size": size, "repeat": rep,
                             "path": str(path.relative_to(ROOT)), "manifest_sha256": file_sha256(path)})
    return grid, cands


def select_statements(per_q: pd.DataFrame, sc: dict) -> pd.DataFrame:
    """Keep statements whose baseline E has room to move both ways; cap at max_keep (closest to 3 first)."""
    per_q = per_q.copy()
    per_q["has_headroom"] = per_q.E_mean.between(sc["e_min"], sc["e_max"])
    ranked = per_q[per_q.has_headroom].assign(dist=lambda d: (d.E_mean - 3).abs()).sort_values("dist")
    keep_ids = set(ranked.id.head(sc["max_keep"]))
    per_q["keep"] = per_q.id.isin(keep_ids)
    per_q["reason"] = [
        "kept" if k else ("dropped: over max_keep" if h else
                          f"dropped: baseline E {e:.2f} outside [{sc['e_min']}, {sc['e_max']}]")
        for k, h, e in zip(per_q.keep, per_q.has_headroom, per_q.E_mean)]
    return per_q


async def _screen(cfg: dict):
    sc = cfg["screen"]
    grid, cands = screen_grid(cfg)
    client = VLMClient(cfg["max_concurrency"])
    results = await call_grouped_by_image(client, grid, cfg, desc="screen")
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCREEN_DIR / "raw.jsonl", "w") as f:
        for g, rec in results:
            f.write(json.dumps({**g, **rec}) + "\n")
    scores = pd.DataFrame([score_row(g, rec) for g, rec in results])
    scores["p_max"] = scores[[f"p{v}" for v in range(1, 6)]].max(axis=1)
    wide = scores.groupby(["qid", "variant"])[["E", "entropy", "p_max"]].mean().unstack("variant")
    wide.columns = [f"{m}_{v}" for m, v in wide.columns]
    wide["E_mean"] = scores.groupby("qid").E.mean()
    per_q = cands.merge(wide.reset_index().rename(columns={"qid": "id"}), on="id")
    per_q = select_statements(per_q, sc)
    per_q.to_csv(SCREEN_DIR / "screen.csv", index=False)
    kept = per_q[per_q.keep][list(cands.columns)]
    out = ROOT / cfg["questions_file"]
    kept.to_csv(out, index=False)
    print(per_q[["id", "source", "axis", "direction", "E_mean", "reason"]].round(2).to_string(index=False))
    print(f"\nKept {len(kept)} of {len(per_q)} -> {out.relative_to(ROOT)}")
    print("  by source:", kept.source.value_counts().to_dict(),
          "| by axis x direction:", kept.groupby(["axis", "direction"]).size().to_dict())
    print_spend(client, results)


def screen(cfg: dict):
    asyncio.run(_screen(cfg))
