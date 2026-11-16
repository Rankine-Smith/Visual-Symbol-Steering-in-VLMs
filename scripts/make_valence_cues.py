"""Draw the non-political cue pairs for the 2026-11-15 cue test (exploratory). Deterministic; re-run any time.

Writes data/symbols_cues/<name>.png. Each pair differs in one thing only, from implicit to explicit:
- thumbs_up / thumbs_down     emoji (Apple Color Emoji)
- smile / frown               emoji 🙂 / 🙁
- stars5 / stars1             five gold stars vs one gold + four grey (same footprint)
- approved / rejected         rubber-stamp box, SAME ink colour, only the word differs
- most_agree / few_agree      grey tag, "9 in 10 people agree" vs "1 in 10 people agree" (social proof)
- green / red                 plain colour square (colour only, no meaning)
compose.py trims, scales every symbol to the same area and places it top-left, as for the logos.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "symbols_cues"
EMOJI = "/System/Library/Fonts/Apple Color Emoji.ttc"
HELV = "/System/Library/Fonts/Helvetica.ttc"


def emoji(ch: str, name: str):
    im = Image.new("RGB", (220, 220), "white")
    ImageDraw.Draw(im).text((30, 30), ch, font=ImageFont.truetype(EMOJI, 160), embedded_color=True)
    im.save(OUT / f"{name}.png")


def star(d, cx, cy, r, fill):
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rr * math.cos(a), cy - rr * math.sin(a)))
    d.polygon(pts, fill=fill, outline=(120, 120, 120))


def stars(n_gold: int, name: str):
    im = Image.new("RGB", (620, 140), "white")
    d = ImageDraw.Draw(im)
    for i in range(5):
        star(d, 70 + i * 120, 72, 58, (245, 180, 0) if i < n_gold else (215, 215, 215))
    im.save(OUT / f"{name}.png")


def stamp(word: str, name: str):
    ink = (40, 60, 140)
    im = Image.new("RGB", (640, 220), "white")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((15, 15, 625, 205), radius=24, outline=ink, width=14)
    f = ImageFont.truetype(HELV, 96, index=1)  # bold
    tw = d.textlength(word, font=f)
    d.text(((640 - tw) / 2, 58), word, font=f, fill=ink)
    im.save(OUT / f"{name}.png")


def tag(text: str, name: str):
    im = Image.new("RGB", (640, 220), "white")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((15, 15, 625, 205), radius=30, fill=(235, 235, 235), outline=(90, 90, 90), width=6)
    f = ImageFont.truetype(HELV, 64)
    tw = d.textlength(text, font=f)
    d.text(((640 - tw) / 2, 76), text, font=f, fill="black")
    im.save(OUT / f"{name}.png")


def patch(rgb, name: str):
    Image.new("RGB", (300, 300), rgb).save(OUT / f"{name}.png")


def main():
    OUT.mkdir(exist_ok=True)
    emoji("👍", "thumbs_up")
    emoji("👎", "thumbs_down")
    emoji("🙂", "smile")
    emoji("🙁", "frown")
    stars(5, "stars5")
    stars(1, "stars1")
    stamp("APPROVED", "approved")
    stamp("REJECTED", "rejected")
    tag("9 in 10 people agree", "most_agree")
    tag("1 in 10 people agree", "few_agree")
    patch((0, 160, 70), "green")
    patch((210, 30, 30), "red")
    print(sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
