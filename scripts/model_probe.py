"""Probe which OpenAI models can be scored like the main experiment (2026-11-15, model-ladder test).

Usage: python scripts/model_probe.py
One P1 call per model on stimuli/q01__none__s0.25.png (through the cached client, so it is logged). For each
model it tries the classic params (max_tokens 1, logprobs, top_logprobs 20) and, if that fails, the
reasoning-off params used for the gpt-6 models. Reports whether first-token logprobs come back, the option
mass on A-E, reasoning tokens and prompt tokens. Writes results/model_probe/probe.csv.
"""
import asyncio
import math
import sys

import pandas as pd

sys.path.insert(0, "src")
from vcb.client import VLMClient, first_top_logprobs  # noqa: E402
from vcb.config import RESULTS_DIR, ROOT  # noqa: E402
from vcb.prompts import P1, prompt_version  # noqa: E402

MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "gpt-5-nano", "gpt-5-mini", "gpt-5", "gpt-5.1",
          "gpt-5.2", "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-5.6-luna", "gpt-5.6-terra",
          "gpt-5.6-sol", "gpt-6-luna", "gpt-6.1-terra", "gpt-6-sol", "gpt-6.1-sol", "gpt-6-astra"]
CLASSIC = {"max_tokens": 1, "logprobs": True, "top_logprobs": 20, "temperature": 1.0}
NOREASON = {"max_completion_tokens": 16, "logprobs": True, "top_logprobs": 5, "temperature": 1.0,
            "reasoning_effort": "none"}
MINIMAL = {**NOREASON, "reasoning_effort": "minimal"}
IMG = ROOT / "stimuli" / "q01__none__s0.25.png"


async def probe(vc, model):
    for name, params in [("classic", CLASSIC), ("noreason", NOREASON), ("minimal", MINIMAL)]:
        try:
            rec = await vc.complete(model=model, prompt_text=P1, prompt_version=prompt_version("P1", P1),
                                    image_path=IMG, detail="high", params=params)
        except Exception as e:  # noqa: BLE001
            last = f"{name}: {type(e).__name__}: {str(e)[:120]}"
            continue
        tops = first_top_logprobs(rec)
        mass = sum(math.exp(t["logprob"]) for t in tops if t["token"].strip() in list("ABCDE"))
        u = rec.get("usage") or {}
        rt = ((u.get("completion_tokens_details") or {}).get("reasoning_tokens"))
        return {"model": model, "params": name, "logprobs": bool(tops), "option_mass": round(mass, 3),
                "content": rec["content"], "reasoning_tokens": rt, "prompt_tokens": u.get("prompt_tokens"),
                "model_returned": rec["model_returned"], "error": ""}
    return {"model": model, "params": "none worked", "error": last}


async def main():
    vc = VLMClient(max_concurrency=8)
    rows = await asyncio.gather(*(probe(vc, m) for m in MODELS))
    df = pd.DataFrame(rows)
    (RESULTS_DIR / "model_probe").mkdir(exist_ok=True)
    df.to_csv(RESULTS_DIR / "model_probe" / "probe.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 90)
    print(df.to_string(index=False))


if __name__ == "__main__":
    asyncio.run(main())
