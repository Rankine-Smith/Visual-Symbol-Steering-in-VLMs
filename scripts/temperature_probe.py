"""Probe (2026-11-14): do the returned first-token logprobs depend on temperature? One image (q21, Republican
logo), P1, each model at several temperatures, 3 calls each. All calls go through the normal cached client."""
import asyncio, math, sys
from vcb.client import VLMClient, first_top_logprobs
from vcb.config import ROOT, load_config
from vcb.prompts import PROMPTS, prompt_version
from vcb.run import logprob_params
from vcb.scoring import score

cfg = load_config(ROOT / "configs/explore/labels.yaml")
IMG = ROOT / "stimuli/q21__republican__s0.25.png"

async def main():
    c = VLMClient(4)
    for model in ["gpt-6-luna", "gpt-4.1-mini"]:
        for T in [0.0, 1.0, 1.5, 2.0]:
            p = {**logprob_params(cfg, model), "temperature": T}
            for rep in range(3):
                try:
                    rec = await c.complete(model=model, prompt_text=PROMPTS["P1"], prompt_version=prompt_version("P1", PROMPTS["P1"]),
                                           image_path=IMG, detail="high", params=p, repeat=rep)
                except Exception as e:
                    print(model, T, "ERROR", str(e)[:150]); break
                tops = first_top_logprobs(rec)
                dist = " ".join(f"{t['token']!r}:{math.exp(t['logprob']):.3f}" for t in tops)
                print(f"{model:13s} T={T} rep{rep} sampled={rec['content'][:8]!r:10s} E={score(tops,'P1')['E']:.3f} | {dist}")
asyncio.run(main())
