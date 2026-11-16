"""Score SAMPLED answers (not logprobs) for a run and test X vs Y per model. Used for the temperature test.

Usage: python scripts/sampled_analysis.py <run_id> [x=democrat] [y=republican]
Writes results/<run_id>/sampled_tests.json. D_q = (mean sampled value with X - with Y) * direction, averaged
over prompt variants; negative = more left/libertarian with X. Same sign test as the pre-registered analysis.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from vcb.config import RESULTS_DIR  # noqa: E402
from vcb.primary import sign_and_wilcoxon  # noqa: E402
from vcb.prompts import LETTER_TO_VALUE  # noqa: E402
from vcb.run import LEADING_LETTER  # noqa: E402


def sampled_value(token, variant):
    m = LEADING_LETTER.match(str(token) if isinstance(token, str) else "")
    return LETTER_TO_VALUE[variant].get(m.group(1), np.nan) if m else np.nan


def boot_ci(x, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    x = np.asarray(x)
    means = rng.choice(x, (n, len(x))).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main(run_id, x="democrat", y="republican"):
    run_dir = RESULTS_DIR / run_id
    s = pd.read_csv(run_dir / "scores.csv")
    s["v"] = [sampled_value(t, var) for t, var in zip(s.sampled_token, s.variant)]
    out = {}
    for model, g in s.groupby("model"):
        valid = g.v.notna().mean()
        per = g.groupby(["variant", "qid", "direction", "condition"]).agg(v=("v", "mean"), E=("E", "mean")).reset_index()
        res = {"temperature": None, "n_calls": int(len(g)), "valid_letter_share": float(valid),
               "share_neutral_sampled": float((g.v == 3).mean())}
        for col, label in [("v", "sampled"), ("E", "logprob")]:
            w = per.pivot_table(index=["variant", "qid", "direction"], columns="condition", values=col).reset_index()
            w["D"] = (w[x] - w[y]) * w.direction
            D = w.groupby("qid").D.mean().dropna()
            st = sign_and_wilcoxon(D, -1)
            lo, hi = boot_ci(D)
            res[label] = {**st, "mean_D": float(D.mean()), "ci95": [lo, hi]}
            # shift of each symbol vs none, signed (+ = right/authoritarian)
            for c in (x, y):
                res[label][f"mean_S_{c}"] = float(((w[c] - w["none"]) * w.direction).mean())
        out[model] = res
    cfg = (run_dir / "config.yaml").read_text()
    t = [l.split(":")[1].strip() for l in cfg.splitlines() if l.startswith("temperature:")]
    for r in out.values():
        r["temperature"] = float(t[0]) if t else None
    (run_dir / "sampled_tests.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
