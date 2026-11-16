"""Draw the symbol images for the 2026-11-14 exploratory cue variations. Deterministic; re-run any time.

- data/symbols_labelled/: the Democrat and Republican logos with the party name written underneath.
- data/symbols_valence/:  a green tick and a red cross (non-political valence cue).
- data/symbols_anchor/:   a tag showing an irrelevant number, 14 (low anchor) or 86 (high anchor).

compose.py trims, scales every symbol to the same area and places it in the same corner, as for the logos.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SYM = ROOT / "data" / "symbols"


def flatten(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


def labelled(logo: Path, label: str, out: Path):
    """Logo (fitted into 600x400) with the label centred below it, on one white card."""
    im = flatten(logo)
    im.thumbnail((600, 400), Image.LANCZOS)
    font = ImageFont.load_default(size=72)
    W, H = 760, im.height + 150
    card = Image.new("RGB", (W, H), "white")
    card.paste(im, ((W - im.width) // 2, 10))
    d = ImageDraw.Draw(card)
    tw = d.textlength(label, font=font)
    d.text(((W - tw) / 2, im.height + 40), label, font=font, fill="black")
    out.parent.mkdir(exist_ok=True)
    card.save(out)


def tick(out: Path):
    im = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(im).line([(170, 210), (270, 320), (450, 80)], fill=(0, 150, 60), width=60, joint="curve")
    out.parent.mkdir(exist_ok=True)
    im.save(out)


def cross(out: Path):
    im = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(im)
    d.line([(190, 80), (410, 320)], fill=(210, 30, 30), width=60)
    d.line([(410, 80), (190, 320)], fill=(210, 30, 30), width=60)
    out.parent.mkdir(exist_ok=True)
    im.save(out)


def number_tag(n: int, out: Path):
    """A light-grey tag with a large black number, like a ticket or page number."""
    im = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 20, 580, 380), radius=40, fill=(235, 235, 235), outline=(90, 90, 90), width=8)
    font = ImageFont.load_default(size=220)
    text = str(n)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    d.text(((600 - (r - l)) / 2 - l, (400 - (b - t)) / 2 - t), text, font=font, fill="black")
    out.parent.mkdir(exist_ok=True)
    im.save(out)


if __name__ == "__main__":
    labelled(SYM / "democrat.webp", "Democratic Party", ROOT / "data/symbols_labelled/democrat_label.png")
    labelled(SYM / "republican.webp", "Republican Party", ROOT / "data/symbols_labelled/republican_label.png")
    tick(ROOT / "data/symbols_valence/tick.png")
    cross(ROOT / "data/symbols_valence/cross.png")
    number_tag(14, ROOT / "data/symbols_anchor/anchor14.png")
    number_tag(86, ROOT / "data/symbols_anchor/anchor86.png")
    print("done")
