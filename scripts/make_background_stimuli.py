"""Logo-as-background stimuli (2026-11-15, exploratory): the party logo fills most of the image and the
statement is printed on top of it.

- Square 1024x1024 white canvas. The Democrat and Republican logos (data/symbols/, trimmed of white borders)
  are scaled to the SAME pixel area, the largest that lets both fit inside a 960x960 box, and centred.
- The statement is rendered once per statement on a transparent layer (black text, 3 px white outline so it
  stays readable on any colour), centred, and pasted identically on every condition.
- `none` = the same text layer on plain white (the baseline).
Writes stimuli_background/ + manifest.csv. `size` is 1.0 only because the pipeline filters on a size column.
"""
import hashlib
import math
import sys
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vcb.compose import flatten_on_white, trim_white  # noqa: E402

OUT = ROOT / "stimuli_background"
QUESTIONS = ROOT / "data" / "questions_background.csv"
W = H = 1024
BOX = 960            # logos must fit inside this centred box
TEXT_W = 820         # max text width
FONT_SIZE = 54
STROKE = 3
LINE_SPACING = 1.3
LOGOS = {"democrat": "democrat.webp", "republican": "republican.webp"}


def wrap(text, font, max_w, draw):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def text_layer(text: str) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = ImageFont.load_default(size=FONT_SIZE)
    lines = wrap(text, font, TEXT_W, d)
    lh = round(FONT_SIZE * LINE_SPACING)
    y = (H - lh * len(lines)) // 2
    for line in lines:
        tw = d.textlength(line, font=font)
        d.text(((W - tw) / 2, y), line, font=font, fill=(0, 0, 0, 255),
               stroke_width=STROKE, stroke_fill=(255, 255, 255, 255))
        y += lh
    return layer


def main():
    logos = {c: trim_white(flatten_on_white(Image.open(ROOT / "data" / "symbols" / f))) for c, f in LOGOS.items()}
    # equal area: the largest area at which every logo still fits in BOX x BOX
    area = min((BOX * min(1, im.height / im.width) * BOX * min(1, im.width / im.height)) for im in logos.values())
    scaled = {}
    for c, im in logos.items():
        a = im.width / im.height
        w, h = round(math.sqrt(area * a)), round(math.sqrt(area / a))
        scaled[c] = im.resize((w, h), Image.LANCZOS)
    OUT.mkdir(exist_ok=True)
    rows = []
    for q in pd.read_csv(QUESTIONS).itertuples():
        txt = text_layer(q.text)
        for cond in ["none", *LOGOS]:
            canvas = Image.new("RGB", (W, H), "white")
            if cond != "none":
                s = scaled[cond]
                canvas.paste(s, ((W - s.width) // 2, (H - s.height) // 2))
            canvas = Image.alpha_composite(canvas.convert("RGBA"), txt).convert("RGB")
            path = OUT / f"{q.id}__{cond}.png"
            canvas.save(path)
            sw, sh = (scaled[cond].width, scaled[cond].height) if cond != "none" else (0, 0)
            rows.append({"qid": q.id, "condition": cond, "size": 1.0, "path": str(path.relative_to(ROOT)),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "symbol_w": sw, "symbol_h": sh,
                         "logo_share_of_canvas": round(sw * sh / (W * H), 3)})
    m = pd.DataFrame(rows)
    m.to_csv(OUT / "manifest.csv", index=False)
    print(m[["qid", "condition", "symbol_w", "symbol_h", "logo_share_of_canvas"]].to_string(index=False))


if __name__ == "__main__":
    main()
