"""Exp B1 summary (2026-11-15 evening, exploratory): frozen manipulation checks for gpt-4.1, gpt-4o and gpt-5.x.

Usage: python scripts/checks_b1_summary.py
Reads results/20261115-checks-b1{,-41cues}/checks_{symbol,transcribe}.csv. Free: no API calls.
Recodes "names the element" with awareness.mention_keywords (cue keyword lists; filename stems such as "stars1"
don't match model text) and adds a false-positive rate on `none` images (any generic visual word such as logo,
symbol, icon, emblem, flag, donkey, elephant ...; strict list FP_WORDS, negated sentences dropped). Writes results/20261115-checks-b1/b1_summary.csv and b1_summary.md.
"""
import re
import sys

import pandas as pd

sys.path.insert(0, "src")
from vcb.awareness import load_keywords, mention_keywords, mentions  # noqa: E402
from vcb.config import RESULTS_DIR  # noqa: E402

RUNS = ["20261115-checks-b1", "20261115-checks-b1-41cues"]
OUT = RESULTS_DIR / RUNS[0]
kw = load_keywords()
sym = pd.concat([pd.read_csv(RESULTS_DIR / r / "checks_symbol.csv") for r in RUNS]).drop_duplicates(
    ["model", "qid", "condition"])
tr = pd.concat([pd.read_csv(RESULTS_DIR / r / "checks_transcribe.csv") for r in RUNS]).drop_duplicates(["model", "qid"])
sym["names_element"] = [bool(mentions(t, mention_keywords(c, kw))) for t, c in zip(sym.text, sym.condition)]
# Strict list: words that would name a corner symbol. GENERIC_VISUAL (colour, corner, ...) also fires on plain images.
FP_WORDS = ["logo", "symbol", "icon", "emblem", "flag", "donkey", "elephant", "animal", "mascot", "thumb", "star",
            "picture of"]  # not "graphic": "a minimal slide-like graphic" describes the whole image
NEG = re.compile(r"\b(no|not|none|without|aside from|other than|nothing)\b", re.I)


def affirmed(text):
    """Text with negated sentences removed ("There are no logos, icons ..." must not count)."""
    return " ".join(s for s in re.split(r"(?<=[.!?\n])\s*", text or "") if not NEG.search(s))


sym["any_visual_word"] = [bool(mentions(affirmed(t), FP_WORDS)) for t in sym.text]
rows = []
for m, x in sym.groupby("model", sort=False):
    r = {"model": m}
    for c in ["democrat", "republican", "thumbs_down", "stars1"]:
        y = x[x.condition == c]
        r[f"names_{c}"] = f"{int(y.names_element.sum())}/{len(y)}" if len(y) else ""
    n = x[x.condition == "none"]
    r["none_false_positive (names any symbol-like element)"] = f"{int(n.any_visual_word.sum())}/{len(n)}"
    t = tr[tr.model == m]
    r["transcribed (ratio >= 0.9)"] = f"{int(t.passed.sum())}/{len(t)}"
    r["mean_transcription_ratio"] = round(t.ratio.mean(), 3)
    rows.append(r)
out = pd.DataFrame(rows)
out.to_csv(OUT / "b1_summary.csv", index=False)
md = ["# Exp B1: manipulation checks (exploratory, frozen check prompts)", "",
      "Describe: \"Describe everything you can see in this image, including any small details.\" on the first 8 ladder "
      "statements per condition; transcribe: all 16 `none` images. Temperature 0. Keyword-coded.", "",
      "| " + " | ".join(out.columns) + " |", "|" + "---|" * len(out.columns),
      *["| " + " | ".join(str(v) for v in r) + " |" for r in out.itertuples(index=False)], ""]
(OUT / "b1_summary.md").write_text("\n".join(md))
print("\n".join(md))
