"""Local typography compositor.

Draws the hook, optional sub-line, optional CTA line and the brand
watermark onto the base image. Doing text locally (not via the image
model) guarantees: readable text, consistent brand, correct watermark,
zero 'AI added random letters' artifacts.

Locked style (creative/master_prompt.txt, STEP 5/6/7):
- thin handwritten font (Caveat), light-to-medium weight only
- soft charcoal ink (#3A3530) on the white plaster background
- LEFT-aligned, starts ~8% from the left edge, upper third, never
  overlapping the subject (QC keeps the subject out of the top third)
- hook larger; sub-line smaller and lighter (65% opacity)
- CTA: plain small low-opacity line near the bottom (never a pill/ad)
- watermark: small signature, bottom corner, low opacity
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import common

EXTRA_FALLBACKS = [
    "C:/Windows/Fonts/segoepr.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _load_font(paths: list[str] | None, size: int) -> ImageFont.FreeTypeFont:
    for p in paths or []:
        if p and Path(p).expanduser().exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    for p in EXTRA_FALLBACKS:
        try:
            if Path(p).exists():
                return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default(size)


def _paths_for(cfg: dict, key: str) -> list[str]:
    t = cfg["typography"]
    out = []
    primary = t.get(key)
    if primary:
        out.append(str(common.ROOT / primary))
    alts = t.get("fallback_fonts")
    if isinstance(alts, list):
        out.extend(str(common.ROOT / g) for g in alts)
    return out


def _hex(rgb: str) -> tuple:
    rgb = rgb.lstrip("#")
    return tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_main(draw, text, font_paths, max_w, lo, hi, max_lines):
    size = lo
    best_lines = None
    while size <= hi:
        font = _load_font(font_paths, size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines:
            best_lines = lines
            probe = size + 4
            if probe > hi:
                break
            font2 = _load_font(font_paths, probe)
            if len(_wrap(draw, text, font2, max_w)) <= max_lines:
                size = probe
                continue
            break
        break
    if best_lines is None:  # still too long at min size: hard wrap
        font = _load_font(font_paths, lo)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            while len(draw.textlength(" ".join(lines[-1:]) + " ...", font=font)) > max_w:
                lines[-1] = lines[-1][:-1]
            lines[-1] += " ..."
        best_lines = lines
        size = lo
    return _load_font(font_paths, size), best_lines, size


def render_post(base_path: Path, out_path: Path, concept: dict, cfg: dict) -> Path:
    canvas = cfg["canvas"]
    ty = cfg["typography"]
    W, H = canvas["width"], canvas["height"]
    ink = _hex(canvas.get("ink", "#3A3530"))

    img = Image.open(base_path).convert("RGB")
    if img.size != (W, H):
        img = img.resize((W, H), Image.LANCZOS)

    main_paths = _paths_for(cfg, "font_main")
    body_paths = _paths_for(cfg, "font_body") or main_paths
    wm_paths = _paths_for(cfg, "font_watermark") or body_paths

    x = int(W * ty.get("left_margin_frac", 0.08))  # ~8% from left edge
    max_w = int(W * (1 - 2 * ty.get("left_margin_frac", 0.08)))

    # ---- main hook (upper third, left-aligned) ----
    draw = ImageDraw.Draw(img)
    hook = concept["hook"]
    font, lines, size = _fit_main(
        draw, hook, main_paths, max_w,
        ty["main_size_min"], ty["main_size_max"], ty["main_max_lines"],
    )
    line_h = size * ty.get("main_line_spacing", 1.05)
    y = ty["text_top"]
    for line in lines:
        draw.text((x, y), line, font=font, fill=ink, anchor="la")
        y += line_h

    # ---- sub-line: smaller and lighter (65% opacity) ----
    sub = (concept.get("subline") or "").strip()
    if sub:
        y += ty.get("block_gap", 44) * 0.5
        fsub = _load_font(body_paths, ty["subline_size"])
        sub_lines = _wrap(draw, sub, fsub, ty.get("subline_max_width", max_w))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        alpha = int(255 * ty.get("subline_opacity", 0.65))
        sy = y
        for line in sub_lines:
            od.text((x, sy), line, font=fsub, fill=ink + (alpha,), anchor="la")
            sy += ty["subline_size"] * 1.2
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

    # ---- CTA: plain small low-opacity line near the bottom (no pill) ----
    cta = (concept.get("cta") or "").strip()
    if cta:
        fcta = _load_font(body_paths, ty.get("cta_size", 42))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        alpha = int(255 * ty.get("cta_opacity", 0.5))
        od.text(
            (x, H - ty.get("cta_bottom_offset", 150)),
            cta, font=fcta, fill=ink + (alpha,), anchor="la",
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

    # ---- watermark: small signature, bottom corner, low opacity ----
    fwm = _load_font(wm_paths, ty["watermark_size"])
    wm_text = canvas["watermark"]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    alpha = int(255 * canvas.get("watermark_opacity", 0.55))
    od.text(
        (W - ty["watermark_margin"], H - ty["watermark_margin"]),
        wm_text, font=fwm, fill=ink + (alpha,), anchor="rs",
    )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    img.save(out_path, "JPEG", quality=93)
    return Path(out_path)
