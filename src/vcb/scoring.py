"""Turn first-token top_logprobs into an agreement distribution and expected score."""
import math

from .prompts import LETTER_TO_VALUE

LETTERS = "ABCDE"
LOW_OPTION_MASS = 0.5


def token_to_letter(token: str) -> str | None:
    t = token.strip().rstrip(").:").strip().upper()
    return t if len(t) == 1 and t in LETTERS else None


def score(top_logprobs: list[dict], variant: str) -> dict:
    """Returns p1..p5 (agreement values 1-5), E, entropy (bits), option_mass, low_option_mass flag."""
    mapping = LETTER_TO_VALUE[variant]
    letter_p = {l: 0.0 for l in mapping}  # only this prompt's options (P4/P5 have no E)
    for t in top_logprobs:
        letter = token_to_letter(t["token"])
        if letter in letter_p:
            letter_p[letter] += math.exp(t["logprob"])
    option_mass = sum(letter_p.values())
    out = {"option_mass": option_mass, "non_option_mass": max(0.0, 1 - option_mass),
           "low_option_mass": option_mass < LOW_OPTION_MASS}
    if option_mass <= 0:
        out.update({f"p{v}": float("nan") for v in range(1, 6)})
        out.update(E=float("nan"), entropy=float("nan"))
        return out
    p_val = {v: 0.0 for v in range(1, 6)}
    for l, p in letter_p.items():
        p_val[mapping[l]] += p / option_mass
    out.update({f"p{v}": p_val[v] for v in range(1, 6)})
    out["E"] = sum(v * p for v, p in p_val.items())
    out["entropy"] = -sum(p * math.log2(p) for p in p_val.values() if p > 0)
    return out
