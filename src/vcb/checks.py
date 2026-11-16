"""Manipulation checks: does the model see the symbol, and does it read the statement?

These are separate fresh single-turn calls, never in the same conversation as the opinion calls, and
are not used in scoring. Plain sampling (no logprobs), temperature 0 for reproducibility.
"""
import asyncio
import difflib
import re

import pandas as pd
from tqdm.asyncio import tqdm_asyncio

from .client import VLMClient
from .config import ROOT, SYMBOLS_DIR, questions_path
from .prompts import CHECK_DESCRIBE, CHECK_TRANSCRIBE, prompt_version
from .run import actual_cost, active_models, run_manifest

CHECK_PARAMS = {"max_tokens": 300, "temperature": 0.0}
N_DESCRIBE_STATEMENTS = 3
TRANSCRIBE_PASS_RATIO = 0.9
BLANK_KEYWORDS = ["grey", "gray", "rectangle", "square", "box", "block"]


def check_params(cfg: dict, model: str) -> dict:
    """Original check params; models with a config `model_params` override (newer models) run with reasoning
    off and max_completion_tokens instead of max_tokens. Unchanged (same cache keys) for the other models."""
    over = (cfg.get("model_params") or {}).get(model)
    if not over:
        return CHECK_PARAMS
    return {"max_completion_tokens": CHECK_PARAMS["max_tokens"], "temperature": CHECK_PARAMS["temperature"],
            **({"reasoning_effort": over["reasoning_effort"]} if "reasoning_effort" in over else {})}


def load_keywords() -> dict[str, list[str]]:
    kw = {}
    path = SYMBOLS_DIR / "keywords.csv"
    if path.exists():
        for r in pd.read_csv(path).itertuples():
            kw[r.symbol] = [k.strip().lower() for k in str(r.keywords).split(";") if k.strip()]
    return kw


def symbol_keywords(symbol: str, extra: dict) -> list[str]:
    """Words from the filename stem plus keywords.csv."""
    stem_words = [w for w in symbol.lower().split("_") if len(w) > 2]
    return sorted(set(stem_words + [symbol.lower().replace("_", " ")] + extra.get(symbol, [])))


def mentions(text: str, keywords: list[str]) -> list[str]:
    t = (text or "").lower()
    return [k for k in keywords if k in t]


def _norm(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip('"\'').strip()


async def _checks(cfg: dict, run_dir):
    # Same statements and conditions as the run (config `conditions`), first size only.
    manifest = run_manifest(cfg)
    manifest = manifest[manifest["size"] == cfg["sizes"][0]]
    questions = pd.read_csv(questions_path(cfg))
    # Config `check_describe_statements` (added 2026-11-15) widens the describe check; default 3 as before.
    first_q = questions.id.tolist()[:cfg.get("check_describe_statements", N_DESCRIBE_STATEMENTS)]
    kw = load_keywords()
    client = VLMClient(cfg["max_concurrency"])
    models = active_models(cfg)
    detail = cfg["image_detail"]
    recs = []

    async def describe(model, row):
        rec = await client.complete(model=model, prompt_text=CHECK_DESCRIBE,
                                    prompt_version=prompt_version("check_describe", CHECK_DESCRIBE),
                                    image_path=ROOT / row.path, detail=detail, params=check_params(cfg, model))
        cond = row.condition
        if cond == "none":
            target, kws = None, []
        elif cond == "blank":
            target, kws = "blank", BLANK_KEYWORDS
        else:
            target = cond.removeprefix("scrambled_")
            kws = symbol_keywords(target, kw)
        hits = mentions(rec["content"], kws)
        recs.append(rec)
        return {"model": model, "qid": row.qid, "condition": cond, "size": row.size,
                "kind": "none" if cond == "none" else "blank" if cond == "blank"
                else "scrambled" if cond.startswith("scrambled_") else "symbol",
                "keywords": ";".join(kws), "hits": ";".join(hits), "mentioned": bool(hits),
                "text": rec["content"], "response_id": rec["response_id"]}

    async def transcribe(model, row, truth):
        rec = await client.complete(model=model, prompt_text=CHECK_TRANSCRIBE,
                                    prompt_version=prompt_version("check_transcribe", CHECK_TRANSCRIBE),
                                    image_path=ROOT / row.path, detail=detail, params=check_params(cfg, model))
        recs.append(rec)
        ratio = difflib.SequenceMatcher(None, _norm(truth), _norm(rec["content"])).ratio()
        return {"model": model, "qid": row.qid, "truth": truth, "text": rec["content"], "ratio": ratio,
                "passed": ratio >= TRANSCRIBE_PASS_RATIO, "response_id": rec["response_id"]}

    desc_rows = [r for r in manifest.itertuples() if r.qid in first_q]
    none_rows = manifest[manifest.condition == "none"]
    truth = questions.set_index("id").text
    tasks = [describe(m, r) for m in models for r in desc_rows]
    tasks += [transcribe(m, r, truth[r.qid]) for m in models for r in none_rows.itertuples()]
    out = await tqdm_asyncio.gather(*tasks, desc="checks")
    sym = pd.DataFrame([o for o in out if "condition" in o])
    tr = pd.DataFrame([o for o in out if "ratio" in o])
    sym.to_csv(run_dir / "checks_symbol.csv", index=False)
    tr.to_csv(run_dir / "checks_transcribe.csv", index=False)
    print(f"API calls made: {client.calls_made}, cache hits: {client.cache_hits}, "
          f"actual cost of new calls: ${actual_cost([r for r in recs if not r.get('cached')]):.3f}")
    return sym, tr


def summarise_checks(sym: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in sorted(set(sym.model) | set(tr.model)):
        s = sym[sym.model == model]
        rows.append({
            "model": model,
            "symbol_seen_rate": s[s.kind == "symbol"].mentioned.mean(),
            "blank_mentioned_rate": s[s.kind == "blank"].mentioned.mean(),
            "scrambled_named_as_source_rate": s[s.kind == "scrambled"].mentioned.mean(),
            "statement_read_rate": tr[tr.model == model].passed.mean(),
            "mean_transcription_ratio": tr[tr.model == model].ratio.mean(),
        })
    return pd.DataFrame(rows)


def run_checks(cfg: dict, run_dir):
    sym, tr = asyncio.run(_checks(cfg, run_dir))
    summ = summarise_checks(sym, tr)
    print(summ.to_string(index=False))
    print("\nSymbol seen, by model x condition:")
    print(sym[sym.kind == "symbol"].pivot_table(index="condition", columns="model", values="mentioned").to_string())
