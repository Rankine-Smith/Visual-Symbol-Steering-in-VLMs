"""Build composite stimulus images: statement in the lower region, optional symbol in the top-left.

Every condition for a statement shares the exact same rendered statement layer; only the symbol slot
differs. Symbols are scaled to equal pixel area and anchored at (24, 24).
"""
import hashlib
import logging
import math

import numpy as np
import pandas as pd
from PIL import Image, ImageChops, ImageDraw, ImageFont

from .config import QUESTION_PNG_DIR, ROOT, SYMBOLS_DIR, load_config, manifest_path, questions_path, stimuli_dir

log = logging.getLogger(__name__)

MARGIN = 24                      # symbol anchor and clamp margin (px)
BORDER_COLOUR = (204, 204, 204)  # 1 px #CCCCCC border on every symbol
BLANK_COLOUR = (128, 128, 128)   # #808080
BASE_FONT_SIZE = 40
MIN_FONT_SIZE = 12
LINE_SPACING = 1.25
SCRAMBLE_SEED = 12345
WHITE_TRIM_THRESHOLD = 12        # pixels within this distance of white count as border


# Top of the statement region as a share of canvas height. 0.42 is the original layout (every run up to
# 2026-11-14 18:50). Configs can set `layout: {question_top: ...}` to move the statement lower and leave
# room for bigger symbols; compose_all applies it. Screening always uses the default.
DEFAULT_QUESTION_TOP = 0.42
_question_top = DEFAULT_QUESTION_TOP


def question_region(W: int, H: int) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1): x 8%-92%, y question_top-92% (default 42%-92%)."""
    return round(0.08 * W), round(_question_top * H), round(0.92 * W), round(0.92 * H)


def symbol_bounds(W: int, H: int) -> tuple[int, int]:
    """Max symbol (w, h): stays inside the area above the question region with a 24 px margin."""
    _, qy0, _, _ = question_region(W, H)
    return W - 2 * MARGIN, qy0 - 2 * MARGIN


# ---------------------------------------------------------------- statement rendering

def _wrap(text: str, font, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _layout(text: str, size: int, region_w: int, region_h: int, draw):
    font = ImageFont.load_default(size=size)
    lines = _wrap(text, font, region_w, draw)
    line_h = round(size * LINE_SPACING)
    widest = max(draw.textlength(l, font=font) for l in lines)
    fits = widest <= region_w and line_h * len(lines) <= region_h
    return font, lines, line_h, fits


def render_statement_layer(text: str, W: int, H: int) -> tuple[Image.Image, int]:
    """White canvas with the statement drawn in the question region. Returns (image, font_size)."""
    canvas = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = question_region(W, H)
    size = BASE_FONT_SIZE
    while True:
        font, lines, line_h, fits = _layout(text, size, x1 - x0, y1 - y0, draw)
        if fits or size <= MIN_FONT_SIZE:
            break
        size -= 2
    if size != BASE_FONT_SIZE:
        log.warning("Statement shrunk to font size %d to fit: %.40s...", size, text)
    y = y0 + ((y1 - y0) - line_h * len(lines)) // 2
    for line in lines:
        draw.text((x0, y), line, font=font, fill="black")
        y += line_h
    return canvas, size


def png_statement_layer(path, W: int, H: int) -> Image.Image:
    """User-supplied question PNG, scaled to fit the question region (aspect kept), centred."""
    canvas = Image.new("RGB", (W, H), "white")
    x0, y0, x1, y1 = question_region(W, H)
    q = flatten_on_white(Image.open(path))
    scale = min((x1 - x0) / q.width, (y1 - y0) / q.height)
    q = q.resize((max(1, round(q.width * scale)), max(1, round(q.height * scale))), Image.LANCZOS)
    canvas.paste(q, (x0 + ((x1 - x0) - q.width) // 2, y0 + ((y1 - y0) - q.height) // 2))
    return canvas


# ---------------------------------------------------------------- symbols

def flatten_on_white(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


def trim_white(im: Image.Image) -> Image.Image:
    """Trim near-white borders (transparent borders become white after flattening).

    We deliberately do NOT trim coloured borders: e.g. the top rows of the Chinese flag are solid red
    and are part of the flag.
    """
    diff = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).convert("L")
    bbox = diff.point(lambda v: 255 if v > WHITE_TRIM_THRESHOLD else 0).getbbox()
    return im.crop(bbox) if bbox else im


def scale_to_area(im: Image.Image, target_area: float, max_w: int, max_h: int):
    """Resize keeping aspect ratio so w*h ~= target_area, clamped to (max_w, max_h)."""
    aspect = im.width / im.height
    w, h = math.sqrt(target_area * aspect), math.sqrt(target_area / aspect)
    clamped = False
    if w > max_w or h > max_h:
        f = min(max_w / w, max_h / h)
        w, h, clamped = w * f, h * f, True
    w, h = max(1, round(w)), max(1, round(h))
    return im.resize((w, h), Image.LANCZOS), clamped


def scramble(im: Image.Image, seed: int = SCRAMBLE_SEED) -> Image.Image:
    """Randomly permute pixels: same size and colour histogram, no meaning."""
    arr = np.asarray(im.convert("RGB"))
    flat = arr.reshape(-1, 3)
    perm = np.random.default_rng(seed).permutation(len(flat))
    return Image.fromarray(flat[perm].reshape(arr.shape))


def place_symbol(canvas: Image.Image, sym: Image.Image) -> tuple[int, int, int, int]:
    """Paste at (24, 24), draw a 1 px border on the symbol's outer edge, return its bbox."""
    W, H = canvas.size
    x0, y0 = MARGIN, MARGIN
    canvas.paste(sym, (x0, y0))
    bbox = (x0, y0, x0 + sym.width, y0 + sym.height)  # exclusive right/bottom
    ImageDraw.Draw(canvas).rectangle((x0, y0, bbox[2] - 1, bbox[3] - 1), outline=BORDER_COLOUR, width=1)
    qx0, qy0, qx1, qy1 = question_region(W, H)
    overlaps = not (bbox[2] <= qx0 or bbox[0] >= qx1 or bbox[3] <= qy0 or bbox[1] >= qy1)
    assert not overlaps, f"Symbol bbox {bbox} intersects question region {(qx0, qy0, qx1, qy1)}"
    return bbox


def load_symbols(symbols_dir=SYMBOLS_DIR) -> dict[str, Image.Image]:
    files = sorted(p for ext in ("png", "jpg", "jpeg", "webp") for p in symbols_dir.glob(f"*.{ext}"))
    return {p.stem: trim_white(flatten_on_white(Image.open(p))) for p in files}


def symbol_conditions(cfg: dict, size: float, symbols: dict, W: int, H: int):
    """Yield (condition, symbol_image_or_None, target_area, clamped) for one size."""
    target_area = (size * W) * (size * W * 2 / 3)
    max_w, max_h = symbol_bounds(W, H)
    yield "none", None, target_area, False
    if cfg.get("include_blank", True):
        blank = Image.new("RGB", (100, 100), BLANK_COLOUR).resize((3, 2))  # 3:2 aspect
        blank, clamped = scale_to_area(blank, target_area, max_w, max_h)
        yield "blank", blank, target_area, clamped
    scaled = {}
    for name, im in symbols.items():
        s, clamped = scale_to_area(im, target_area, max_w, max_h)
        if clamped:
            log.warning("Symbol %s clamped at size %s: area %d < target %d", name, size, s.width * s.height, target_area)
        scaled[name] = (s, clamped)
        yield name, s, target_area, clamped
    if cfg.get("include_scrambled", True):
        for name, (s, clamped) in scaled.items():
            yield f"scrambled_{name}", scramble(s), target_area, clamped


def compose_all(cfg: dict | None = None) -> pd.DataFrame:
    global _question_top
    cfg = cfg or load_config()
    _question_top = (cfg.get("layout") or {}).get("question_top", DEFAULT_QUESTION_TOP)
    STIMULI_DIR = stimuli_dir(cfg)
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    questions = pd.read_csv(questions_path(cfg))
    # Config `symbols_dir` (relative to the project root) lets a side experiment use its own symbol set.
    sym_dir = ROOT / cfg["symbols_dir"] if cfg.get("symbols_dir") else SYMBOLS_DIR
    symbols = load_symbols(sym_dir)
    if not symbols:
        raise SystemExit(f"No symbols found in {sym_dir}")
    STIMULI_DIR.mkdir(exist_ok=True)
    rows = []
    for q in questions.itertuples():
        png = QUESTION_PNG_DIR / f"{q.id}.png"
        if png.exists():
            base, font_size, source = png_statement_layer(png, W, H), None, "png"
        else:
            base, font_size = render_statement_layer(q.text, W, H)
            source = "rendered"
        for size in cfg["sizes"]:
            for cond, sym, target_area, clamped in symbol_conditions(cfg, size, symbols, W, H):
                canvas = base.copy()
                bbox = place_symbol(canvas, sym) if sym is not None else None
                path = STIMULI_DIR / f"{q.id}__{cond}__s{size}.png"
                canvas.save(path, format="PNG", optimize=False)
                rows.append({
                    "qid": q.id, "condition": cond, "size": size,
                    "path": str(path.relative_to(STIMULI_DIR.parent)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "symbol_w": sym.width if sym is not None else 0,
                    "symbol_h": sym.height if sym is not None else 0,
                    "symbol_area": sym.width * sym.height if sym is not None else 0,
                    "target_area": round(target_area) if sym is not None else 0,
                    "clamped": bool(clamped),
                    "symbol_bbox": str(bbox) if bbox else "",
                    "font_size": font_size, "statement_source": source,
                })
    manifest = pd.DataFrame(rows)
    manifest.to_csv(manifest_path(cfg), index=False)
    return manifest
