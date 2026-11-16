"""Turn the team's pre-assembled photo stimuli (data/pre_assembled/*.jpeg) into a stimulus folder the normal
pipeline can run (2026-11-15, exploratory).

The JPEGs are decoded and saved as PNG (the client sends every image as image/png), so the pixels the model
sees are exactly the decoded JPEG. The originals are not touched. Writes stimuli_preassembled/ + manifest.csv.
size is set to 1.0 only because the pipeline filters on a size column; these images have no symbol-size setting.
"""
import hashlib
from pathlib import Path

import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "pre_assembled"
OUT = ROOT / "stimuli_preassembled"
QID = {"q4": "q04", "q5": "q05"}
COND = {"dem": "democrat", "rep": "republican"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for src in sorted(SRC.glob("*.jpeg")):
        q, c = src.stem.split("_")
        qid, cond = QID[q], COND[c]
        out = OUT / f"{qid}__{cond}.png"
        im = Image.open(src).convert("RGB")
        im.save(out)
        rows.append({"qid": qid, "condition": cond, "size": 1.0, "path": str(out.relative_to(ROOT)),
                     "sha256": sha(out), "width": im.width, "height": im.height,
                     "source_file": str(src.relative_to(ROOT)), "source_sha256": sha(src)})
    pd.DataFrame(rows).to_csv(OUT / "manifest.csv", index=False)
    print(pd.DataFrame(rows)[["qid", "condition", "path", "width", "height"]].to_string(index=False))


if __name__ == "__main__":
    main()
